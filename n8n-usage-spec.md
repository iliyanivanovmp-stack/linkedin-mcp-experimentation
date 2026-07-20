# LinkedIn MCP — n8n Usage Spec

**Endpoint:** `https://iliyan-ivanov-mp--linkedin-mcp-linkedin-mcp-server.modal.run/mcp`  
**Method:** `POST`  
**Content-Type:** `application/json`

---

## Request Format

Every call is a JSON-RPC 2.0 `tools/call`:

```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "<tool_name>",
    "arguments": { }
  },
  "id": 1
}
```

---

## Tool Call Examples

### search_people
```json
{
  "jsonrpc": "2.0", "method": "tools/call", "id": 1,
  "params": {
    "name": "search_people",
    "arguments": {
      "keywords": "growth marketing SaaS",
      "location": "London",
      "network": "S"
    }
  }
}
```
`network`: `"F"` = 1st degree, `"S"` = 2nd degree, `"O"` = 3rd+

---

### get_person_profile
```json
{
  "jsonrpc": "2.0", "method": "tools/call", "id": 1,
  "params": {
    "name": "get_person_profile",
    "arguments": {
      "linkedin_username": "john-doe-123",
      "sections": ["experience", "contact_info"]
    }
  }
}
```
Only request the sections you need — each section = 1 extra page load.

---

### get_company_profile
```json
{
  "jsonrpc": "2.0", "method": "tools/call", "id": 1,
  "params": {
    "name": "get_company_profile",
    "arguments": {
      "company_name": "openai"
    }
  }
}
```
Returns `company_urn` — pass it to `search_people` as `current_company` to filter by company.

---

### search_jobs
```json
{
  "jsonrpc": "2.0", "method": "tools/call", "id": 1,
  "params": {
    "name": "search_jobs",
    "arguments": {
      "keywords": "head of growth",
      "location": "United States",
      "date_posted": "past_week"
    }
  }
}
```

---

### get_feed
```json
{
  "jsonrpc": "2.0", "method": "tools/call", "id": 1,
  "params": {
    "name": "get_feed",
    "arguments": { "num_posts": 20 }
  }
}
```

---

### send_message
```json
{
  "jsonrpc": "2.0", "method": "tools/call", "id": 1,
  "params": {
    "name": "send_message",
    "arguments": {
      "linkedin_username": "john-doe-123",
      "message": "Hey John, ...",
      "confirm_send": true
    }
  }
}
```
`confirm_send` must be `true` — the server rejects the call without it.

---

### close_session
```json
{
  "jsonrpc": "2.0", "method": "tools/call", "id": 1,
  "params": {
    "name": "close_session",
    "arguments": {}
  }
}
```
Call at the end of every workflow that used LinkedIn tools.

---

## n8n Workflow Pattern

```
Trigger
  → HTTP Request (LinkedIn tool call)
  → Wait (10–15s)          ← mandatory between calls
  → HTTP Request (next tool)
  → Wait (10–15s)
  → ...
  → HTTP Request (close_session)
```

**HTTP Request node settings:**
- Method: `POST`
- URL: endpoint above
- Body Content Type: `JSON`
- Body: paste the JSON-RPC block for the tool you want

**Response:** the tool result is in `response.result.content[0].text` (JSON string, parse it).

---

## Safety Rules

| Rule | Value |
|------|-------|
| Delay between calls | 10–15s minimum |
| Max profiles per run | 15 |
| Min time between workflow runs | 30 min |
| Max list size to loop over | 10 items |
| `confirm_send` on send_message | always `true` |
| `connect_with_person` | never use |
