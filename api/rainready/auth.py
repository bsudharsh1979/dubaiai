"""Server-side identity and RBAC.

The browser only holds a signed session cookie that names a user id.  Role,
organisation and jurisdiction scope are always read from the ``users`` table on
the server; nothing the client sends (headers, JSON fields, model output) can
grant a permission.  The demo identity switcher exists only when
``DEMO_AUTH=true`` and ``APP_ENV != production``.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User

ROLES = {
    "drainage_controller": "Municipal drainage controller",
    "utility_engineer": "Utility duty engineer",
    "transport_controller": "Transport controller",
    "incident_commander": "Emergency incident commander",
    "hse_officer": "HSE officer",
    "field_inspector": "Field inspector",
}

# Human authority required for each privileged action kind.  These are
# *proposed* role mappings for the demonstration, not an agency's policy.
ACTION_AUTHORITY: dict[str, set[str]] = {
    "inspection": {"drainage_controller", "incident_commander"},
    "pump_deployment": {"drainage_controller", "incident_commander"},
    "access_control": {"transport_controller", "incident_commander"},
    "advisory": {"incident_commander"},
    "utility_investigation": {"utility_engineer", "incident_commander"},
    "hse_review": {"hse_officer", "incident_commander"},
}

PERMISSIONS: dict[str, set[str]] = {
    "incident:read": set(ROLES),
    "incident:create": {"drainage_controller", "utility_engineer", "incident_commander", "hse_officer", "transport_controller"},
    "incident:close": {"incident_commander"},
    "incident:cancel": {"incident_commander"},
    "field_report:submit": set(ROLES),
    "field_report:review": {"hse_officer", "drainage_controller", "incident_commander", "utility_engineer"},
    "twin:control": {"drainage_controller", "incident_commander", "hse_officer", "utility_engineer", "transport_controller"},
    "import:raster": {"drainage_controller", "incident_commander"},
    "audit:export": {"incident_commander", "hse_officer"},
    "emergency_stop": {"incident_commander"},
    "scenario:run": {"drainage_controller", "utility_engineer", "incident_commander", "hse_officer", "transport_controller"},
    "workorder:ack": {"drainage_controller", "utility_engineer", "transport_controller", "hse_officer", "incident_commander"},
    "assistant:ask": set(ROLES),
    "knowledge:read": set(ROLES),
}


@dataclass
class Identity:
    id: str
    name: str
    role: str
    organisation: str
    jurisdictions: list[str]

    def can(self, permission: str) -> bool:
        return self.role in PERMISSIONS.get(permission, set())

    def may_approve(self, action_kind: str) -> bool:
        return self.role in ACTION_AUTHORITY.get(action_kind, set())

    def in_scope(self, jurisdiction: str) -> bool:
        return "*" in self.jurisdictions or jurisdiction in self.jurisdictions

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "role": self.role, "role_label": ROLES.get(self.role, self.role),
                "organisation": self.organisation, "jurisdictions": self.jurisdictions,
                "permissions": sorted(p for p, roles in PERMISSIONS.items() if self.role in roles),
                "approval_authority": sorted(k for k, roles in ACTION_AUTHORITY.items() if self.role in roles)}


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().session_secret, salt="rainready-session")


def set_session(response: Response, user_id: str) -> None:
    s = get_settings()
    token = _serializer().dumps({"uid": user_id})
    response.set_cookie(s.session_cookie_name, token, max_age=s.session_max_age_s, httponly=True, samesite="lax", secure=s.cookie_secure, path="/")


def clear_session(response: Response) -> None:
    response.delete_cookie(get_settings().session_cookie_name, path="/")


def load_identity(request: Request, db: Session) -> Identity | None:
    s = get_settings()
    token = request.cookies.get(s.session_cookie_name)
    if not token:
        return None
    try:
        data = _serializer().loads(token, max_age=s.session_max_age_s)
    except (BadSignature, SignatureExpired):
        return None
    user = db.get(User, data.get("uid", ""))
    if not user or not user.active:
        return None
    return Identity(id=user.id, name=user.name, role=user.role, organisation=user.organisation, jurisdictions=list(user.jurisdictions or []))


def current_identity(request: Request, db: Session = Depends(get_db)) -> Identity:
    ident = load_identity(request, db)
    if ident is None:
        raise HTTPException(status_code=401, detail="Not signed in", headers={"X-Error-Code": "unauthenticated"})
    return ident


def optional_identity(request: Request, db: Session = Depends(get_db)) -> Identity | None:
    return load_identity(request, db)


def require(permission: str):
    def _dep(ident: Identity = Depends(current_identity)) -> Identity:
        if not ident.can(permission):
            raise HTTPException(status_code=403, detail=f"Role '{ident.role}' lacks permission '{permission}'")
        return ident
    return _dep
