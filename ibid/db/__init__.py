# Copyright (c) 2009-2011, Stefano Rivera
# Released under terms of the MIT/X/Expat Licence. See COPYING for details.
import warnings as _warnings

from ibid.db.types import TypeDecorator, Integer, DateTime, Boolean, \
                          IbidUnicode, IbidUnicodeText

from sqlalchemy import Table, Column, ForeignKey, Index, UniqueConstraint, \
                       server_default, or_, and_, MetaData as _MetaData
from sqlalchemy.orm import eagerload, relation, synonym
from sqlalchemy.sql import func
from sqlalchemy.ext.declarative import declarative_base as _declarative_base

from sqlalchemy.exceptions import IntegrityError, SADeprecationWarning

metadata = _MetaData()
Base = _declarative_base(metadata=metadata)

from ibid.db.versioned_schema import VersionedSchema, SchemaVersionException, \
                                     schema_version_check, upgrade_schemas

# We use SQLAlchemy 0.4 compatible .save_or_update() functions
_warnings.filterwarnings('ignore', 'Use session.add\(\)', SADeprecationWarning)

def get_regexp_op(session):
    "Return a regexp operator"
    if session.bind.engine.name in ('postgres', 'postgresql'):
        return lambda x, y: x.op('~')(y)
    else:
        return lambda x, y: x.op('REGEXP')(y)

# vi: set et sta sw=4 ts=4:
