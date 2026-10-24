---
doc_id: SOP-COMMS-REVIEW
version: 0.2-demo
title: Communication drafting and review (demonstration procedure)
collection: comms
access_roles: communications_officer, incident_coordinator, assurance_officer, incident_commander
---
> DEMONSTRATION PROCEDURE for the RainReady UAE prototype. Not an official communications policy.

## S1 Templates
Advisories are drafted from approved templates: area, hazard label (e.g. "forecast risk of waterlogging"), expected window, requested public behaviour, and the issuing authority placeholder. Drafts must use the incident's label verbatim; "observed water" and "forecast risk" are never merged.

## S2 Sensitive details
Public text must not name sensitive assets (substations, control rooms) or give internal asset identifiers. Use area descriptions instead.

## S3 Arabic drafts
Arabic text produced by a template or a model is a draft until a reviewer marks it reviewed. Both languages are shown side by side for approval; the approval binds the exact text.

## S4 Publication
The communications persona cannot publish. Publication is a human-approved action executed by the simulated advisory connector in this MVP; the approval binds the recipients, the area and the canonical text hash. Edits after approval invalidate the approval.

## T1 Template — waterlogging advisory (EN)
"{area}: {label}. Surface water may accumulate between {window_start} and {window_end} (Asia/Dubai). Avoid the underpass at {location} and follow directions from authorities. This message is based on forecast scenario modelling and will be updated."

## T2 Template — waterlogging advisory (AR, draft)
"{area}: {label_ar}. قد تتجمع المياه السطحية بين {window_start} و{window_end} (توقيت دبي). تجنّب النفق في {location} واتبع تعليمات الجهات المختصة. تستند هذه الرسالة إلى نمذجة سيناريو توقّعية وسيتم تحديثها."
