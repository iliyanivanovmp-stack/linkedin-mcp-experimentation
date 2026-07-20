# Keyword Pain Conversations

Runs one narrow pain keyword at a time and exports only first-person buyer pain.

The first test used `drowning in admin`. Five posts were checked and all five
were correctly rejected as sellers, educational posts, case studies, or wrong
geography. Zero is the correct output when no buyer qualifies.

Run through the shared social-post provider:

```bash
python signals/common/social_post_signal.py \
  --config signals/keyword-pain-conversations/config.json \
  --output signals/exports/signal_leads.csv
```
