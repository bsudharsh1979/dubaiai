from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..auth import ROLES, Identity, clear_session, current_identity, set_session
from ..config import get_settings
from ..db import get_db
from ..models import User
from ..schemas import DemoLogin, GenericOk, IdentityOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me", response_model=IdentityOut)
def me(ident: Identity = Depends(current_identity)):
    return ident.as_dict()


@router.get("/identities")
def identities(db: Session = Depends(get_db)):
    """Demo-only list of selectable identities.  Selecting one still results in a server-signed session."""
    s = get_settings()
    if not s.demo_identity_switcher_enabled:
        raise HTTPException(status_code=404, detail="identity switcher disabled")
    rows = db.execute(select(User).where(User.active.is_(True))).scalars().all()
    return {"demo_mode": True, "identities": [{"id": u.id, "name": u.name, "role": u.role, "role_label": ROLES.get(u.role, u.role), "organisation": u.organisation} for u in rows]}


@router.post("/demo-login", response_model=IdentityOut)
def demo_login(body: DemoLogin, response: Response, db: Session = Depends(get_db)):
    s = get_settings()
    if not s.demo_identity_switcher_enabled:
        raise HTTPException(status_code=403, detail="demo login disabled")
    u = db.get(User, body.user_id)
    if not u or not u.active:
        raise HTTPException(status_code=404, detail="unknown demo identity")
    set_session(response, u.id)
    audit.record(db, u.id, "auth.demo_login", "user", u.id, {"role": u.role})
    return Identity(id=u.id, name=u.name, role=u.role, organisation=u.organisation, jurisdictions=list(u.jurisdictions or [])).as_dict()


@router.post("/logout", response_model=GenericOk)
def logout(response: Response):
    clear_session(response)
    return GenericOk()
