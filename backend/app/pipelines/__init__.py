"""Foundry-style visual pipeline builder.

A pipeline is a DAG of typed nodes connected by edges. The compiler turns
the graph into a single read-only SQL statement (CTE chain). The service
materializes the result as a Postgres VIEW in the managed schema
``mf_pipelines`` and registers a corresponding logical Dataset row so that
dashboards, notebooks, and AI consumers see pipeline outputs as
first-class catalog entries.
"""
