# -------------------------------------------------------------
# NDN Hydra Global View
# -------------------------------------------------------------
#  @Project: NDN Hydra
#  @Date:    2021-01-25
#  @Authors: Please check AUTHORS.rst
#  @Source-Code:   https://github.com/justincpresley/ndn-hydra
#  @Documentation: https://ndn-hydra.readthedocs.io
#  @Pip-Library:   https://pypi.org/project/ndn-hydra
# -------------------------------------------------------------

import os
import sqlite3
from sqlite3 import Error
from typing import List, Tuple

sql_create_nodes_tables = """
CREATE TABLE IF NOT EXISTS nodes (
    node_name TEXT PRIMARY KEY,
    favor REAL NOT NULL,
    state_vector INTEGER NOT NULL,
    expired INTEGER NOT NULL
);
"""
sql_create_files_tables = """
CREATE TABLE IF NOT EXISTS files (
    file_name TEXT PRIMARY KEY,
    desired_copies INTEGER NOT NULL DEFAULT 3,
    packets INTEGER NOT NULL DEFAULT 1,
    digests BLOB NOT NULL DEFAULT 0,
    size INTEGER NOT NULL,
    origin_node_name TEXT NOT NULL,
    fetch_path TEXT NOT NULL,
    state_vector INTEGER NOT NULL,
    is_deleted INTEGER NOT NULL DEFAULT 0
);
"""
sql_create_stored_by_tables = """
CREATE TABLE IF NOT EXISTS stored_by (
    id INTEGER PRIMARY KEY,
    file_name TEXT NOT NULL,
    node_name NOT NULL
);
"""
sql_create_backuped_by_tables = """
CREATE TABLE IF NOT EXISTS backuped_by (
    id INTEGER PRIMARY KEY,
    file_name TEXT NOT NULL,
    node_name NOT NULL,
    rank INTEGER NOT NULL,
    nonce TEXT NOT NULL
);
"""
sql_create_pending_stores_tables = """
CREATE TABLE IF NOT EXISTS pending_stores (
    id INTEGER PRIMARY KEY,
    file_name TEXT NOT NULL,
    node_name NOT NULL
);
"""

class GlobalView:
    def __init__(self, db:str):
        self.db = os.path.expanduser(db)
        if len(os.path.dirname(self.db)) > 0 and not os.path.exists(os.path.dirname(self.db)):
            try:
                os.makedirs(os.path.dirname(self.db))
            except PermissionError:
                raise PermissionError(f'Could not create database directory: {self.db}') from None
            except FileExistsError:
                pass
        self.__create_tables()
    def __get_connection(self):
        try:
            return sqlite3.connect(self.db)
        except Error as e:
            print(e)
            return None
    def __execute_sql(self, sql:str):
        result = []
        conn = self.__get_connection()
        if conn is not None:
            try:
                c = conn.cursor()
                c.execute(sql)
                conn.commit()
                result = c.fetchall()
            except Error as e:
                print(e)
            conn.close()
        return result
    def __execute_sql_qmark(self, sql:str, par:Tuple):
        result = []
        conn = self.__get_connection()
        if conn is not None:
            try:
                c = conn.cursor()
                c.execute(sql, par)
                conn.commit()
                result = c.fetchall()
            except Error as e:
                print(e)
            conn.close()
        return result
    def __create_tables(self):
        self.__execute_sql(sql_create_nodes_tables)
        self.__execute_sql(sql_create_files_tables)
        self.__execute_sql(sql_create_stored_by_tables)
        self.__execute_sql(sql_create_backuped_by_tables)
        self.__execute_sql(sql_create_pending_stores_tables)

    def __rerank_backuped_by(self, file_name:str, node_name:str):
        # check rank
        sql_get_backup = """
        SELECT DISTINCT file_name, node_name, rank
        FROM backuped_by
        WHERE (file_name = ?) AND (node_name = ?)
        """
        result = self.__execute_sql_qmark(sql_get_backup, (file_name, node_name))
        # return result
        rank = -1
        if len(result) == 1:
            rank = result[0][2]
        if rank != -1:
            sql_rerank = """
            UPDATE backuped_by
            SET rank = rank - 1
            WHERE (file_name = ?) AND (rank > ?)
            """
            self.__execute_sql_qmark(sql_rerank, (file_name, rank))

    def get_node(self, node_name:str):
        sql = """
        SELECT DISTINCT node_name, favor, state_vector, expired
        FROM nodes
        WHERE node_name = ?
        """
        result = self.__execute_sql_qmark(sql, (node_name, ))
        if len(result) != 1:
            return None
        else:
            return {
                'node_name': result[0][0],
                'favor': result[0][1],
                'state_vector': result[0][2],
                'expired': False if (result[0][3] == 0) else True
            }

    def get_nodes(self, include_expired:bool=False):
        if include_expired:
            sql = """
            SELECT DISTINCT node_name, favor, state_vector, expired
            FROM nodes
            """
        else:
            sql = """
            SELECT DISTINCT node_name, favor, state_vector, expired
            FROM nodes
            WHERE expired = 0
            """
        results = self.__execute_sql(sql)
        nodes = []
        for result in results:
            nodes.append({
                'node_name': result[0],
                'favor': result[1],
                'state_vector': result[2],
                'expired': False if (result[3] == 0) else True
            })
        return nodes

    def update_node(self, node_name:str, favor:float, state_vector:int):
        sql = """
        INSERT OR REPLACE INTO nodes
            (node_name, favor, state_vector, expired)
        VALUES
            (?, ?, ?, COALESCE((SELECT expired FROM nodes WHERE node_name = ?), 1))
        """
        self.__execute_sql_qmark(sql, (node_name, favor, state_vector, node_name))

    def renew_node(self, node_name:str):
        sql = """
        UPDATE nodes
        SET expired = 0
        WHERE node_name = ?
        """
        self.__execute_sql_qmark(sql, (node_name, ))

    def expire_node(self, node_name:str):
        # stored_by
        sql_stored_by = """
        DELETE FROM stored_by WHERE node_name = ?
        """
        self.__execute_sql_qmark(sql_stored_by, (node_name, ))
        # backuped_by
        sql_get_backups = """
        SELECT file_name, node_name
        FROM backuped_by
        WHERE node_name = ?
        """
        backups = self.__execute_sql_qmark(sql_get_backups, (node_name, ))
        for backup in backups:
            # rerank
            self.__rerank_backuped_by(backup[0], node_name)
        # remove
        sql_delete_backuped_by = """
        DELETE FROM backuped_by WHERE node_name = ?
        """
        self.__execute_sql_qmark(sql_delete_backuped_by, (node_name, ))
        # pending_stores
        sql_pending_stores = """
        DELETE FROM pending_stores WHERE node_name = ?
        """
        self.__execute_sql_qmark(sql_pending_stores, (node_name, ))
        # expire session
        sql = """
        UPDATE nodes
        SET expired = 1
        WHERE node_name = ?
        """
        self.__execute_sql_qmark(sql, (node_name, ))

    def __split_digests(self, digests:bytes, size:int):
        digests_bytes = bytes(digests)
        return [digests_bytes[i:i+size] for i in range(0, len(digests_bytes), size)]

    def get_file(self, file_name:str):
        sql = """
        SELECT DISTINCT
            file_name, desired_copies, packets, size, origin_node_name, fetch_path, state_vector, is_deleted, digests
        FROM files
        WHERE file_name = ?
        """
        result = self.__execute_sql_qmark(sql, (file_name, ))
        if len(result) != 1:
            return None
        else:
            return {
                'file_name': result[0][0],
                'desired_copies': result[0][1],
                'packets': result[0][2],
                'size': result[0][3],
                'origin_node_name': result[0][4],
                'fetch_path': result[0][5],
                'state_vector': result[0][6],
                'is_deleted': False if (result[0][7] == 0) else True,
                'digests': self.__split_digests(result[0][8], 2),
                'stored_bys': self.get_stored_bys(result[0][0]),
                'backuped_bys': self.get_backuped_bys(result[0][0])
            }

    def get_files(self, including_deleted:bool=False):
        if including_deleted:
            sql = """
            SELECT DISTINCT
                file_name, desired_copies, packets, size, origin_node_name, fetch_path, state_vector, is_deleted, digests
            FROM files
            """
        else:
            sql = """
            SELECT DISTINCT
                file_name, desired_copies, packets, size, origin_node_name, fetch_path, state_vector, is_deleted, digests
            FROM files
            WHERE is_deleted = 0
            """
        results = self.__execute_sql(sql)
        files = []
        for result in results:
            files.append({
                'file_name': result[0],
                'desired_copies': result[1],
                'packets': result[2],
                'size': result[3],
                'origin_node_name': result[4],
                'fetch_path': result[5],
                'state_vector': result[6],
                'is_deleted': False if (result[7] == 0) else True,
                'digests': self.__split_digests(result[8], 2),
                'stored_bys': self.get_stored_bys(result[0]),
                'backuped_bys': self.get_backuped_bys(result[0])
            })
        return files

    def get_underreplicated_files(self):
        files = self.get_files()
        underreplicated_files = []
        for file in files:
            if len(file['stored_bys']) < file['desired_copies']:
                underreplicated_files.append(file)
        return underreplicated_files

    def get_backupable_files(self):
        files = self.get_files()
        backupable_files = []
        for file in files:
            if( len(file['stored_bys']) + len(file['backuped_bys']) ) < (file['desired_copies'] * 2):
                backupable_files.append(file)
        return backupable_files

    def add_file(self, file_name:str, size:int, origin_node_name:str, fetch_path:str, state_vector:int,
                digests:bytes, packets:int=1, desired_copies:int=3):
        sql = """
        INSERT OR IGNORE INTO files
            (file_name, desired_copies, packets, size, origin_node_name, fetch_path, state_vector, is_deleted, digests)
        VALUES
            (?, ?, ?, ?, ?, ?, ?, 0, ?)
        """
        self.__execute_sql_qmark(sql, (file_name, desired_copies, packets, size, origin_node_name, fetch_path, state_vector, digests))

    def delete_file(self, file_name:str):
        # stored_by
        sql_stored_by = """
        DELETE FROM stored_by WHERE file_name = ?
        """
        self.__execute_sql_qmark(sql_stored_by, (file_name, ))

        # backuped_by
        sql_backuped_by = """
        DELETE FROM backuped_by WHERE file_name = ?
        """
        self.__execute_sql_qmark(sql_backuped_by, (file_name, ))

        # backuped_by
        sql_get_backups = """
        SELECT DISTINCT file_name, node_name
        FROM backuped_by
        WHERE file_name = ?
        """
        backups = self.__execute_sql_qmark(sql_get_backups, (file_name, ))
        for backup in backups:
            # rerank
            self.__rerank_backuped_by(file_name, backup[1])
        # remove
        sql_delete_backuped_by = """
        DELETE FROM backuped_by WHERE file_name = ?
        """
        self.__execute_sql_qmark(sql_delete_backuped_by, (file_name, ))

        # pending_stores
        sql_pending_stores = """
        DELETE FROM pending_stores WHERE file_name = ?
        """
        self.__execute_sql_qmark(sql_pending_stores, (file_name, ))

        # insertions
        sql_files = """
        UPDATE files
        SET is_deleted = 1
        WHERE file_name = ?
        """
        self.__execute_sql_qmark(sql_files, (file_name, ))

    def store_file(self, file_name:str, node_name:str):
        # rerank backuped_by
        self.__rerank_backuped_by(file_name, node_name)
        # remove from backuped_by
        sql_delete_backuped_by = """
        DELETE FROM backuped_by WHERE (file_name = ?) AND (node_name = ?)
        """
        self.__execute_sql_qmark(sql_delete_backuped_by, (file_name, node_name))
        # add to stored_by
        sql_add_to_stored_by = """
        INSERT OR IGNORE INTO stored_by
            (file_name, node_name)
        VALUES
            (?, ?)
        """
        self.__execute_sql_qmark(sql_add_to_stored_by, (file_name, node_name))

    def set_backups(self, file_name:str, backup_list:List[Tuple[str, str]]):
        # remove previous backups
        sql_delete_backuped_by = """
        DELETE FROM backuped_by WHERE (file_name = ?)
        """
        self.__execute_sql_qmark(sql_delete_backuped_by, (file_name, ))
        # add backups
        length = len(backup_list)
        for rank in range(length):
            backup = backup_list[rank]
            sql_add_backup = """
            INSERT OR IGNORE INTO backuped_by
                (file_name, node_name, rank, nonce)
            VALUES
                (?, ?, ?, ?)
            """
            self.__execute_sql_qmark(sql_add_backup, (file_name, backup[0], rank, backup[1]))

    def add_backup(self, file_name:str, node_name:str, rank:int, nonce:str):
        # delete all backups with larger rank value
        sql_delete_backuped_by = """
        DELETE FROM backuped_by
        WHERE (file_name = ?) AND rank >= ?
        """
        self.__execute_sql_qmark(sql_delete_backuped_by, (file_name, rank))
        # add this backup
        sql_add_backup = """
        INSERT OR IGNORE INTO backuped_by
            (file_name, node_name, rank, nonce)
        VALUES
            (?, ?, ?, ?)
        """
        self.__execute_sql_qmark(sql_add_backup, (file_name, node_name, rank, nonce))

    def get_stored_bys(self, file_name:str):
        sql = """
        SELECT DISTINCT file_name, node_name
        FROM stored_by
        WHERE file_name = ?
        ORDER BY node_name ASC
        """
        results = self.__execute_sql_qmark(sql, (file_name, ))
        stored_bys = []
        for result in results:
            stored_bys.append(result[1])
        return stored_bys

    def get_backuped_bys(self, file_name:str):
        sql = """
        SELECT DISTINCT file_name, node_name, rank, nonce
        FROM backuped_by
        WHERE file_name = ?
        ORDER BY rank
        """
        results = self.__execute_sql_qmark(sql, (file_name, ))
        backuped_bys = []
        for result in results:
            backuped_bys.append({
                'node_name': result[1],
                'rank': result[2],
                'nonce': result[3]
            })
        return backuped_bys

    def get_pending_stores(self, file_name:str):
        sql = """
        SELECT DISTINCT file_name, node_name
        FROM pending_stores
        WHERE file_name = ?
        """
        results = self.__execute_sql_qmark(sql, (file_name, ))
        pending_stores = []
        for result in results:
            pending_stores.append(result[1])
        return pending_stores

    def add_pending_store(self, file_name:str, node_name:str):
        sql = """
        INSERT OR IGNORE INTO pending_stores
            (file_name, node_name)
        VALUES
            (?, ?)
        """
        self.__execute_sql_qmark(sql, (file_name, node_name))
