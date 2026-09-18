The system shall support user login.

- REQ-001: WHEN a user submits a form, the system shall validate all required fields.
- REQ-002: WHILE a session is active, the system shall refresh tokens automatically.
- REQ-003: IF a user exceeds 5 failed attempts, THEN the system shall lock the account.

| 需求 ID | 验收标准 | 测试方法 |
|--------|---------|---------|
| REQ-001 | 必填字段校验通过 | 单元测试 |
| REQ-002 | Token 自动刷新 | 单元测试 |
| REQ-003 | 账号锁定 30 分钟 | 集成测试 |