-- Layer 3 / Production target-state grant model (account groups).
--
-- This is the grant model a real payer deployment uses: UC privileges granted to
-- account-level groups, which UC resolves as first-class principals and which
-- identity-federate across workspaces. It is the posture 02_apply_governance.py
-- would apply verbatim if run by an account admin.
--
-- It is NOT executed in this sandbox: the build identity is a workspace admin, not
-- an account admin, so account groups cannot be created here, and UC rejects grants
-- to workspace-local groups (PRINCIPAL_DOES_NOT_EXIST). The live build therefore
-- grants the same privileges to the persona service principals instead (see
-- 02_apply_governance.py section 6). The mask/row-filter policy is identical either
-- way: it keys on is_member() over these same group names.
--
-- To promote to production: have an account admin create the five groups below and
-- assign them to the workspace, then run this script. No other change is required.

-- Catalog access ------------------------------------------------------------
GRANT USE CATALOG ON CATALOG zrb_fe_bar_uhc_stars_catalog TO `zrb_stars_care_coordinators`;
GRANT USE CATALOG ON CATALOG zrb_fe_bar_uhc_stars_catalog TO `zrb_stars_quality_analysts`;
GRANT USE CATALOG ON CATALOG zrb_fe_bar_uhc_stars_catalog TO `zrb_stars_data_engineers`;
GRANT USE CATALOG ON CATALOG zrb_fe_bar_uhc_stars_catalog TO `zrb_stars_phi_authorized`;
GRANT USE CATALOG ON CATALOG zrb_fe_bar_uhc_stars_catalog TO `zrb_stars_admins`;
GRANT MANAGE      ON CATALOG zrb_fe_bar_uhc_stars_catalog TO `zrb_stars_admins`;

-- Raw medallion: engineers read + write; break-glass + admins read. Coordinators
-- and analysts get nothing here (they consume the governed zone only).
GRANT USE SCHEMA, SELECT ON SCHEMA zrb_fe_bar_uhc_stars_catalog.bronze TO `zrb_stars_data_engineers`;
GRANT USE SCHEMA, SELECT ON SCHEMA zrb_fe_bar_uhc_stars_catalog.silver TO `zrb_stars_data_engineers`;
GRANT USE SCHEMA, SELECT ON SCHEMA zrb_fe_bar_uhc_stars_catalog.gold   TO `zrb_stars_data_engineers`;
GRANT MODIFY ON SCHEMA zrb_fe_bar_uhc_stars_catalog.bronze TO `zrb_stars_data_engineers`;
GRANT MODIFY ON SCHEMA zrb_fe_bar_uhc_stars_catalog.silver TO `zrb_stars_data_engineers`;
GRANT MODIFY ON SCHEMA zrb_fe_bar_uhc_stars_catalog.gold   TO `zrb_stars_data_engineers`;
GRANT USE SCHEMA, SELECT ON SCHEMA zrb_fe_bar_uhc_stars_catalog.bronze TO `zrb_stars_phi_authorized`;
GRANT USE SCHEMA, SELECT ON SCHEMA zrb_fe_bar_uhc_stars_catalog.silver TO `zrb_stars_phi_authorized`;
GRANT USE SCHEMA, SELECT ON SCHEMA zrb_fe_bar_uhc_stars_catalog.gold   TO `zrb_stars_phi_authorized`;
GRANT USE SCHEMA, SELECT ON SCHEMA zrb_fe_bar_uhc_stars_catalog.bronze TO `zrb_stars_admins`;
GRANT USE SCHEMA, SELECT ON SCHEMA zrb_fe_bar_uhc_stars_catalog.silver TO `zrb_stars_admins`;
GRANT USE SCHEMA, SELECT ON SCHEMA zrb_fe_bar_uhc_stars_catalog.gold   TO `zrb_stars_admins`;

-- Governance consumption zone ----------------------------------------------
GRANT USE SCHEMA ON SCHEMA zrb_fe_bar_uhc_stars_catalog.governance TO `zrb_stars_care_coordinators`;
GRANT USE SCHEMA ON SCHEMA zrb_fe_bar_uhc_stars_catalog.governance TO `zrb_stars_quality_analysts`;
GRANT USE SCHEMA ON SCHEMA zrb_fe_bar_uhc_stars_catalog.governance TO `zrb_stars_data_engineers`;
GRANT USE SCHEMA ON SCHEMA zrb_fe_bar_uhc_stars_catalog.governance TO `zrb_stars_phi_authorized`;
GRANT USE SCHEMA ON SCHEMA zrb_fe_bar_uhc_stars_catalog.governance TO `zrb_stars_admins`;

-- Worklist: coordinators + analysts + break-glass + admins.
GRANT SELECT ON TABLE zrb_fe_bar_uhc_stars_catalog.governance.care_gaps TO `zrb_stars_care_coordinators`;
GRANT SELECT ON TABLE zrb_fe_bar_uhc_stars_catalog.governance.care_gaps TO `zrb_stars_quality_analysts`;
GRANT SELECT ON TABLE zrb_fe_bar_uhc_stars_catalog.governance.care_gaps TO `zrb_stars_phi_authorized`;
GRANT SELECT ON TABLE zrb_fe_bar_uhc_stars_catalog.governance.care_gaps TO `zrb_stars_admins`;

-- Labs: analysts + break-glass + admins (coordinators do not need raw labs).
GRANT SELECT ON TABLE zrb_fe_bar_uhc_stars_catalog.governance.member_labs TO `zrb_stars_quality_analysts`;
GRANT SELECT ON TABLE zrb_fe_bar_uhc_stars_catalog.governance.member_labs TO `zrb_stars_phi_authorized`;
GRANT SELECT ON TABLE zrb_fe_bar_uhc_stars_catalog.governance.member_labs TO `zrb_stars_admins`;

-- coordinator_scope holds RLS configuration, not consumer data: no grants beyond owner/admins.
