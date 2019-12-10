# -*- coding: utf-8 -*-
# Copyright 2014-2016 OpenMarket Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import os
from textwrap import indent
from typing import List

import yaml

from twisted.enterprise import adbapi

from synapse.config._base import Config, ConfigError
from synapse.storage.engines import create_engine


class DatabaseConnectionConfig(object):
    """Contains the connection config for a particular database.

    Args:
        name: A label for the database, used for logging.
        db_config: The config for a particular database, as per `database`
            section of main config. Has two fields: `name` for database
            module name, and `args` for the args to give to the database
            connector.
        data_stores: The list of data stores that should be provisioned on the
            database.
    """

    def __init__(self, name: str, db_config: dict, data_stores: List[str]):
        if db_config["name"] not in ("sqlite3", "psycopg2"):
            raise ConfigError("Unsupported database type %r" % (db_config["name"],))

        if db_config["name"] == "sqlite3":
            db_config.setdefault("args", {}).update(
                {"cp_min": 1, "cp_max": 1, "check_same_thread": False}
            )

        self.name = name
        self.config = db_config
        self.data_stores = data_stores

        self.engine = create_engine(db_config)
        self.config["args"]["cp_openfun"] = self.engine.on_new_connection

        self._pool = None

    def get_pool(self, reactor) -> adbapi.ConnectionPool:
        """Get the connection pool for the database.
        """

        if self._pool is None:
            self._pool = adbapi.ConnectionPool(
                self.config["name"], cp_reactor=reactor, **self.config.get("args", {})
            )

        return self._pool

    def make_conn(self):
        """Make a new connection to the database and return it.

        Returns:
            Connection
        """

        db_params = {
            k: v
            for k, v in self.config.get("args", {}).items()
            if not k.startswith("cp_")
        }
        db_conn = self.engine.module.connect(**db_params)
        return db_conn


class DatabaseConfig(Config):
    section = "database"

    def read_config(self, config, **kwargs):
        self.event_cache_size = self.parse_size(config.get("event_cache_size", "10K"))

        self.database_config = config.get("database")

        if self.database_config is None:
            self.database_config = {"name": "sqlite3", "args": {}}

        name = self.database_config.get("name", None)
        if name == "psycopg2":
            pass
        elif name == "sqlite3":
            self.database_config.setdefault("args", {}).update(
                {"cp_min": 1, "cp_max": 1, "check_same_thread": False}
            )
        else:
            raise RuntimeError("Unsupported database type '%s'" % (name,))

        self.set_databasepath(config.get("database_path"))

    def generate_config_section(self, data_dir_path, database_conf, **kwargs):
        if not database_conf:
            database_path = os.path.join(data_dir_path, "homeserver.db")
            database_conf = (
                """# The database engine name
          name: "sqlite3"
          # Arguments to pass to the engine
          args:
            # Path to the database
            database: "%(database_path)s"
            """
                % locals()
            )
        else:
            database_conf = indent(yaml.dump(database_conf), " " * 10).lstrip()

        return (
            """\
        ## Database ##

        database:
          %(database_conf)s
        # Number of events to cache in memory.
        #
        #event_cache_size: 10K
        """
            % locals()
        )

    def read_arguments(self, args):
        self.set_databasepath(args.database_path)

    def set_databasepath(self, database_path):
        if database_path != ":memory:":
            database_path = self.abspath(database_path)
        if self.database_config.get("name", None) == "sqlite3":
            if database_path is not None:
                self.database_config["args"]["database"] = database_path

    @staticmethod
    def add_arguments(parser):
        db_group = parser.add_argument_group("database")
        db_group.add_argument(
            "-d",
            "--database-path",
            metavar="SQLITE_DATABASE_PATH",
            help="The path to a sqlite database to use.",
        )
