from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from flask import Blueprint, Flask


_REGISTRATION_EXTENSION_KEY = "sgaa_legacy_route_blueprints"
_BUSINESS_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})


class LegacyRouteRegistrationError(RuntimeError):
    """Raised when transitional legacy routes cannot be registered unambiguously."""


@dataclass(frozen=True, slots=True)
class LegacyRouteSpec:
    rule: str
    endpoint: str
    view_func: Callable
    methods: tuple[str, ...]

    def __post_init__(self) -> None:
        rule = str(self.rule or "").strip()
        endpoint = str(self.endpoint or "").strip()
        methods = tuple(str(method).upper().strip() for method in self.methods)
        if not rule.startswith("/"):
            raise LegacyRouteRegistrationError(f"Invalid legacy route rule: {self.rule!r}")
        if not endpoint or "." in endpoint:
            raise LegacyRouteRegistrationError(
                f"Invalid legacy endpoint; a global legacy name is required: {self.endpoint!r}"
            )
        if not callable(self.view_func):
            raise LegacyRouteRegistrationError(
                f"Legacy route view is not callable: endpoint={endpoint}"
            )
        if not methods or len(set(methods)) != len(methods):
            raise LegacyRouteRegistrationError(
                f"Legacy route methods must be non-empty and unique: endpoint={endpoint}"
            )
        if any(method not in _BUSINESS_METHODS for method in methods):
            raise LegacyRouteRegistrationError(
                f"Unsupported legacy route method: endpoint={endpoint} methods={methods!r}"
            )
        object.__setattr__(self, "rule", rule)
        object.__setattr__(self, "endpoint", endpoint)
        object.__setattr__(self, "methods", methods)


def _validate_spec_set(specs: tuple[LegacyRouteSpec, ...]) -> None:
    if not specs:
        raise LegacyRouteRegistrationError("At least one legacy route specification is required")

    endpoints: set[str] = set()
    rule_methods: set[tuple[str, str]] = set()
    for spec in specs:
        if spec.endpoint in endpoints:
            raise LegacyRouteRegistrationError(
                f"Duplicate legacy endpoint specification: {spec.endpoint}"
            )
        endpoints.add(spec.endpoint)
        for method in spec.methods:
            key = (spec.rule, method)
            if key in rule_methods:
                raise LegacyRouteRegistrationError(
                    f"Duplicate legacy rule/method specification: {spec.rule} {method}"
                )
            rule_methods.add(key)


def _registered_blueprint_names(app: Flask) -> frozenset[str]:
    return frozenset(app.extensions.get(_REGISTRATION_EXTENSION_KEY, ()))


def _validate_app_collisions(
    app: Flask,
    blueprint: Blueprint,
    specs: tuple[LegacyRouteSpec, ...],
) -> None:
    if blueprint.name in _registered_blueprint_names(app):
        raise LegacyRouteRegistrationError(
            f"Legacy blueprint already registered on this application: {blueprint.name}"
        )

    existing_rules = tuple(app.url_map.iter_rules())
    for spec in specs:
        if spec.endpoint in app.view_functions:
            raise LegacyRouteRegistrationError(
                f"Legacy endpoint collision: endpoint={spec.endpoint}"
            )
        requested_methods = set(spec.methods)
        for existing in existing_rules:
            if existing.rule != spec.rule:
                continue
            existing_methods = set(existing.methods or ()) & _BUSINESS_METHODS
            overlap = requested_methods & existing_methods
            if overlap:
                methods = ",".join(sorted(overlap))
                raise LegacyRouteRegistrationError(
                    "Legacy rule/method collision: "
                    f"rule={spec.rule} methods={methods} "
                    f"existing_endpoint={existing.endpoint} requested_endpoint={spec.endpoint}"
                )


def configure_legacy_routes(
    blueprint: Blueprint,
    specs: Iterable[LegacyRouteSpec],
) -> tuple[LegacyRouteSpec, ...]:
    """Attach one immutable legacy-route set to a blueprint via ``record_once``."""

    frozen_specs = tuple(specs)
    _validate_spec_set(frozen_specs)
    if hasattr(blueprint, "_sgaa_legacy_route_specs"):
        raise LegacyRouteRegistrationError(
            f"Legacy routes already configured for blueprint: {blueprint.name}"
        )
    blueprint._sgaa_legacy_route_specs = frozen_specs  # type: ignore[attr-defined]

    @blueprint.record_once
    def _register_legacy_routes(state) -> None:
        app = state.app
        _validate_app_collisions(app, blueprint, frozen_specs)
        for spec in frozen_specs:
            app.add_url_rule(
                spec.rule,
                endpoint=spec.endpoint,
                view_func=spec.view_func,
                methods=spec.methods,
            )
        registered = set(_registered_blueprint_names(app))
        registered.add(blueprint.name)
        app.extensions[_REGISTRATION_EXTENSION_KEY] = registered

    return frozen_specs


def register_legacy_blueprint(app: Flask, blueprint: Blueprint) -> None:
    """Register a configured legacy blueprint after a fail-closed preflight."""

    specs = getattr(blueprint, "_sgaa_legacy_route_specs", None)
    if not isinstance(specs, tuple):
        raise LegacyRouteRegistrationError(
            f"Blueprint has no configured legacy route specifications: {blueprint.name}"
        )
    _validate_app_collisions(app, blueprint, specs)
    app.register_blueprint(blueprint)


__all__ = [
    "LegacyRouteRegistrationError",
    "LegacyRouteSpec",
    "configure_legacy_routes",
    "register_legacy_blueprint",
]
