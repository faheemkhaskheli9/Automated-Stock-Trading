"""Shared owner/staff queryset scoping, used by every operator-UI app.

The rule is the same everywhere in this project: a plain user sees only rows
tied to their own `Account` (via some ORM path ending at `owner`); staff see
everything. `api.views.OwnerScopedMixin` implements this for DRF viewsets;
`scope_to_owner` is the same rule for plain Django FBVs (portfolio, execution,
risk, ...) so the predicate lives in exactly one place instead of being
hand-copied per app.
"""

from __future__ import annotations

from django.db.models import Q, QuerySet
from django.http import HttpRequest


def scope_to_owner(qs: QuerySet, request: HttpRequest, owner_lookup: str = "owner") -> QuerySet:
    """Restrict ``qs`` to rows owned by ``request.user``, via ``owner_lookup``
    (an ORM path ending at an `Account`'s `owner`, e.g. ``"owner"`` or
    ``"account__owner"``). Staff bypass the filter and see everything."""
    if request.user.is_staff:
        return qs
    return qs.filter(Q(**{owner_lookup: request.user}))
