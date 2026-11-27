"""Pydantic v2 request/response schemas.

Request models forbid unknown fields so clients cannot smuggle attributes the
server does not understand; response models are documented explicitly rather
than exposing ORM internals wholesale.
"""
