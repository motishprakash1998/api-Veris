-- =============================
-- Enums
-- =============================
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'role_enum') THEN
        CREATE TYPE role_enum AS ENUM ('employee', 'superadmin');
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'status_enum') THEN
        CREATE TYPE status_enum AS ENUM ('active', 'inactive');
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'gender_enum') THEN
        CREATE TYPE gender_enum AS ENUM ('male', 'female', 'other');
    END IF;
END $$;

-- =============================
-- Timestamp helper: auto-update updated_at
-- =============================
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at := NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =============================
-- employees
-- =============================
CREATE TABLE IF NOT EXISTS employees (
    id               BIGSERIAL PRIMARY KEY,
    email            VARCHAR(255)        NOT NULL,
    password_hash    TEXT                NOT NULL,                      -- store hashed password
    role             role_enum           NOT NULL DEFAULT 'employee',
    status           status_enum         NOT NULL DEFAULT 'active',
    created_at       TIMESTAMPTZ         NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ         NOT NULL DEFAULT NOW(),
    CONSTRAINT employees_email_unique UNIQUE (email)
    );

CREATE INDEX IF NOT EXISTS idx_employees_status ON employees(status);
CREATE INDEX IF NOT EXISTS idx_employees_role ON employees(role);

CREATE TRIGGER trg_employees_set_updated_at
BEFORE UPDATE ON employees
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Optional: enforce case-insensitive uniqueness robustly
-- (CITEXT + unique already covers it)

-- =============================
-- employee_profiles (1:1 with employees)
-- =============================
CREATE TABLE IF NOT EXISTS employee_profiles (
    id                 BIGSERIAL PRIMARY KEY,
    employee_id        BIGINT              NOT NULL UNIQUE
                                         REFERENCES employees(id) ON DELETE CASCADE,
    first_name         VARCHAR(100)        NOT NULL,
    last_name          VARCHAR(100)        NOT NULL,
    phone_number       VARCHAR(20),
    date_of_birth      DATE,
    gender             gender_enum,
    address            TEXT,
    state              VARCHAR(100),
    country            VARCHAR(100),
    pin_code           VARCHAR(20),
    profile_path       TEXT                 NOT NULL DEFAULT 'profile_pictures/default.png',
    emergency_contact  VARCHAR(20),
    profile_completed  BOOLEAN              NOT NULL DEFAULT FALSE,
    created_at         TIMESTAMPTZ          NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ          NOT NULL DEFAULT NOW(),
    CONSTRAINT profiles_phone_e164_chk CHECK (
        phone_number IS NULL OR phone_number ~ '^\+?[1-9]\d{1,14}$'
    ),
    CONSTRAINT profiles_emerg_e164_chk CHECK (
        emergency_contact IS NULL OR emergency_contact ~ '^\+?[1-9]\d{1,14}$'
    )
);

CREATE INDEX IF NOT EXISTS idx_employee_profiles_employee_id ON employee_profiles(employee_id);

CREATE TRIGGER trg_employee_profiles_set_updated_at
BEFORE UPDATE ON employee_profiles
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =============================
-- employee_devices (for FCM tokens / sessions)
-- =============================
CREATE TABLE IF NOT EXISTS employee_devices (
    id             BIGSERIAL PRIMARY KEY,
    employee_id    BIGINT        NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    fcm_token      TEXT          NOT NULL,
    last_seen_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    UNIQUE (employee_id, fcm_token)
);

CREATE INDEX IF NOT EXISTS idx_employee_devices_emp ON employee_devices(employee_id);

-- =============================
-- password_reset_tokens
-- =============================
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id            BIGSERIAL PRIMARY KEY,
    employee_id   BIGINT       NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    token         TEXT         NOT NULL UNIQUE,
    expires_at    TIMESTAMPTZ  NOT NULL,
    used_at       TIMESTAMPTZ,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT reset_token_not_used_before_expiry CHECK (
        used_at IS NULL OR used_at <= expires_at
    )
);

CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_emp ON password_reset_tokens(employee_id);
CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_expires ON password_reset_tokens(expires_at);

-- =============================
-- Helpful views (optional)
-- =============================
CREATE OR REPLACE VIEW v_employee_with_profile AS
SELECT
    e.id,
    e.email,
    e.role,
    e.status,
    p.first_name,
    p.last_name,
    p.phone_number AS profile_phone,
    p.date_of_birth,
    p.gender,
    p.address,
    p.state,
    p.country,
    p.pin_code,
    p.profile_path,
    p.emergency_contact,
    p.profile_completed,
    e.created_at AS employee_created_at,
    e.updated_at AS employee_updated_at,
    p.created_at AS profile_created_at,
    p.updated_at AS profile_updated_at
FROM employees e
LEFT JOIN employee_profiles p ON p.employee_id = e.id;
