ALTER TABLE operator_audit_events
    DROP CONSTRAINT IF EXISTS operator_audit_events_action_check;

ALTER TABLE operator_audit_events
    ADD CONSTRAINT operator_audit_events_action_check
    CHECK (action IN (
        'model_promotion',
        'model_rollback',
        'audit_attestation_key_rotation'
    ));
