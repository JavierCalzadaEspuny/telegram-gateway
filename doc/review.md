# TelegramGateway technical review

## Scope

This review covers the 1.4.0 working-tree changes to the package, its
documentation, and the two inspected consumers: Telegram-OSINT and
Telegram-OSINT-backtest-lab. The consumer repositories were not changed. No
real Telegram requests or account performance measurements were made.

## Changes

- TelegramHistory uses messages.translateText(peer=..., id=[...]) to translate
  up to 20 messages per request, bounded by 25,000 UTF-16 code units of source
  text. These thresholds follow Telegram's Android client; they are not
  published server limits. For 2,000 short messages, the initial request count
  falls from roughly 2,000 to 100. Text size and retries can increase it.
- History retries timeouts, known server errors, and the exact
  TRANSLATE_REQ_QUOTA_EXCEEDED error with bounded backoff. It respects
  Telegram's FloodWait duration. Translation still fails open: a successful
  fetch does not guarantee a translation for every eligible message.
- TelegramListener resolves channel filters at startup, waits on the client's
  disconnection future without disconnecting the borrowed client, and cancels
  its own processing tasks on shutdown. It keeps individual-message
  translation and does not add Gateway retries.
- TelegramMessage exposes has_media and reply_to_message_id. Media detection
  uses fields already present on each message; it downloads no attachments.
  The reply text is not fetched. Existing positional constructor arguments
  retain their order, and the new optional fields are appended.
- Photo downloads explicitly select a still-image size. Channel matching
  accepts an optional leading @ and ignores case.
- The package version is 1.4.0. Its empty py.typed marker is included in the
  wheel. to_dict() presents identity, channel, message and reply, text, and
  media in groups.

## Known limitations

- Telegram may still deny or delay translation. Retries are finite, and no
  increase to Premium quota is assumed.
- History uses the first message in an album for its identity and text. A
  caption on a later album item is not selected.
- reply_to_message_id does not contain a peer ID for cross-chat replies, or
  the root message ID for a topic.
- Listener reads Telethon 1.45's private _updates_error to preserve fatal
  update errors while awaiting the public disconnection future. Review this
  compatibility point when upgrading Telethon.
- Historical retrieval returns current message contents. It cannot reconstruct
  edits or recover deleted messages for a past-time backtest.

## Consumer integration

Both consumer projects currently pin Gateway to commit
7a75e75234e8a0007d1ba4d47088af6bc985e36a; they will not receive these local
changes until their dependency references and lockfiles point to a published
revision. The backtest project currently stores and queries original text, so
using translations requires a coordinated dataset and replay change. The live
project consumes image bytes for OCR but currently drops message_id,
has_media, and reply_to_message_id in its DTO.

## Verification limits

Compilation, lockfile consistency, wheel construction, package import, and
documentation links can be checked locally without contacting Telegram. They
do not prove a specific RPC reduction in wall-clock time, an account's quota,
or complete translation coverage. Measure those with the intended account and
workload.
