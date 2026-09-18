# API error envelope

Application errors under `/api/v1` use JSON and a stable top-level `error`
member:

```json
{
  "error": {
    "code": "work_order_version_conflict",
    "message": "The work order changed; refresh and retry.",
    "request_id": "01K5FQ2PVPEFM0ZE9S8DQ42GAT",
    "fields": [
      {
        "field": "version",
        "code": "stale"
      }
    ]
  }
}
```

`code` is a documented machine-readable identifier. `message` is safe for an
end user and must not include credentials, dependency responses, stack traces,
SQL, object keys, or internal database IDs. `request_id` identifies the request
in structured logs. `fields` is optional and contains only allowlisted input
paths and validation codes.

Clients must branch on HTTP status and `code`, not message text. Unknown routes,
framework validation failures, authorization failures, concurrency conflicts,
rate limits, and internal failures will be adapted to this envelope when the v1
application routes are introduced. Health endpoints are operational contracts,
not application errors: readiness returns a safe per-dependency state with HTTP
503 and does not expose failure details.

The Phase 2 organization reference routes use these stable codes:

| Status | Code | Meaning |
| --- | --- | --- |
| 401 | `authentication_required` | No verified request-scoped tenant context |
| 403 | `forbidden` | Tenant context lacks the required capability |
| 404 | `organization_not_found` | The resource is absent or belongs to another tenant |
| 409 | `transaction_conflict` | A uniqueness or transactional invariant rejected the mutation |
| 422 | `validation_error` | The request body or path is invalid |

The 404 response deliberately does not distinguish an absent UUID from a UUID
owned by another organization.
