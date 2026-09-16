-- Run as the database owner after MCP/OAuth migrations. Pass app_user,
-- app_password and database_name through psql variables; never echo secrets.
SELECT format('CREATE ROLE %I LOGIN', :'app_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user')
\gexec
SELECT format('ALTER ROLE %I WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 24 PASSWORD %L', :'app_user', :'app_password')
\gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', :'database_name', :'app_user')
\gexec
SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'app_user')
\gexec
SELECT format('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM %I', :'app_user')
\gexec
SELECT format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM %I', :'app_user')
\gexec
SELECT format('REVOKE CREATE ON SCHEMA public FROM %I', :'app_user')
\gexec
SELECT format('GRANT SELECT ON TABLE %I TO %I', tablename, :'app_user')
FROM pg_tables WHERE schemaname='public' AND tablename IN (
 'users_user','users_role','users_permission','users_role_permissions','users_restaurantprofile','users_adminmfaprofile',
 'restaurants_restaurant','restaurants_cashdesk',
 'platform_restaurantentitlement','platform_restaurantentitlement_permissions','platform_tariff','platform_tariff_permissions',
 'sales_order','sales_orderitem',
 'billing_payment','billing_paymentrefund','billing_receipt','billing_cashshift','billing_cashexpense',
 'catalog_catalogitem','catalog_catalogcategory',
 'floor_tablesession','floor_diningtable','floor_hall',
 'oauth2_provider_application','django_migrations','django_site'
)
\gexec
GRANT UPDATE(last_login) ON users_user TO :"app_user";
GRANT UPDATE(last_totp_counter,last_totp_code_digest) ON users_adminmfaprofile TO :"app_user";
SELECT format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %I TO %I', tablename, :'app_user')
FROM pg_tables WHERE schemaname='public' AND (
 tablename LIKE 'analytics_mcp\_%' ESCAPE '\'
 OR (tablename LIKE 'oauth2_provider\_%' ESCAPE '\' AND tablename != 'oauth2_provider_application')
 OR tablename='django_session'
)
\gexec
SELECT format('GRANT USAGE, SELECT ON SEQUENCE %I TO %I', sequencename, :'app_user')
FROM pg_sequences WHERE schemaname='public' AND (
 sequencename LIKE 'analytics_mcp\_%' ESCAPE '\'
 OR (sequencename LIKE 'oauth2_provider\_%' ESCAPE '\' AND sequencename != 'oauth2_provider_application_id_seq')
)
\gexec
SELECT format('ALTER ROLE %I SET statement_timeout TO %L', :'app_user', '15s')
\gexec
SELECT format('ALTER ROLE %I SET lock_timeout TO %L', :'app_user', '3s')
\gexec
