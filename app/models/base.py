# path: app/models/base.py


# DeclarativeBase:
# Modern SQLAlchemy 2.0 base class used for ORM models.
#
# All database tables/models inherit from this.
from sqlalchemy.orm import DeclarativeBase


# Column:
# Used to define table columns
#
# DateTime:
# SQL datetime datatype
#
# func:
# SQL functions like NOW(), COUNT(), etc.
from sqlalchemy import Column, DateTime, func



# =========================================================
# BASE MODEL CLASS
# =========================================================

# Every SQLAlchemy model/table in the project
# will inherit from this Base class.
#
# Example:
#
# class Job(Base):
#     ...
#
# DeclarativeBase automatically provides:
#
# - metadata tracking
# - ORM mapping
# - table registration
#
# SQLAlchemy internally keeps track of all models
# through Base.metadata
#
# Later used for:
#
# Base.metadata.create_all(bind=engine)
#
# which creates all database tables.
class Base(DeclarativeBase):

    """
    Root base class for all SQLAlchemy ORM models.

    Any table/model in the application must inherit from this.

    SQLAlchemy uses this class to:
    - register tables
    - map Python objects to DB tables
    - manage metadata
    """

    # pass means:
    # no additional logic is currently needed
    pass



# =========================================================
# TIMESTAMP MIXIN
# =========================================================

# A mixin is a reusable class containing shared fields or logic.
#
# Instead of repeating:
#
# created_at
# updated_at
#
# in every model,
# we define them once here.
#
# Example:
#
# class Job(Base, TimestampMixin):
#     ...
#
# Now Job automatically gets:
#
# - created_at
# - updated_at
#
# This is a very common production backend pattern.
class TimestampMixin:

    """
    Reusable timestamp fields for audit tracking.

    Add this mixin to any model that needs:
    - creation timestamp
    - update timestamp

    Example:
        class Job(Base, TimestampMixin):
            ...
    """



    # =====================================================
    # CREATED_AT COLUMN
    # =====================================================

    # created_at stores the timestamp
    # when the row was first inserted.
    #
    # DateTime(timezone=True):
    # Stores timezone-aware timestamps.
    #
    # Extremely important in production systems
    # where servers/users may exist in different timezones.
    #
    # server_default=func.now():
    # PostgreSQL itself sets the timestamp.
    #
    # Equivalent SQL:
    #
    # created_at TIMESTAMP DEFAULT NOW()
    #
    # Better than setting timestamp in Python because:
    #
    # - DB becomes source of truth
    # - avoids server clock mismatch
    # - consistent across environments
    #
    # nullable=False:
    # This column cannot be NULL.
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )



    # =====================================================
    # UPDATED_AT COLUMN
    # =====================================================

    # updated_at stores the timestamp
    # of the latest modification.
    #
    # server_default=func.now():
    # Sets initial timestamp during INSERT.
    #
    # onupdate=func.now():
    # Automatically updates timestamp whenever row changes.
    #
    # Example:
    #
    # UPDATE jobs SET title='AI Engineer'
    #
    # updated_at automatically becomes current timestamp.
    #
    # This is useful for:
    #
    # - auditing
    # - debugging
    # - tracking changes
    # - ETL pipelines
    # - analytics
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )