# Hermes photoagent profile

This folder contains the Hermes profile instructions for connecting Telegram to `photo-ingest-agent`.

Target workflow:

1. User inserts a memory card into the Mac mini.
2. User sends a Telegram message in the photo-agent channel, such as `최신 사진 가져와줘`.
3. Hermes profile `photoagent` runs `scripts/hermes_photo_bridge.py ingest-latest`.
4. The bridge finds the latest photo date on the card, copies only that date to the SSD, writes detailed notes, stages JPG files for Lightroom Classic Auto Import, and prints a short Korean result.

Install/update locally:

```bash
cp integrations/hermes/photoagent/SOUL.md ~/.hermes/profiles/photoagent/SOUL.md
cp integrations/hermes/photoagent/config.yaml ~/.hermes/profiles/photoagent/config.yaml
cp integrations/hermes/photoagent/.env.example ~/.hermes/profiles/photoagent/.env.example
```

Do not copy an existing Hermes profile `.env` into this profile. Use a separate bot token or separate Telegram channel ID.

Manual test:

```bash
/Users/jinito/Workspaces/photo-ingest-agent/scripts/hermes_photo_bridge.py status
/Users/jinito/Workspaces/photo-ingest-agent/scripts/hermes_photo_bridge.py ingest-latest
/Users/jinito/Workspaces/photo-ingest-agent/scripts/hermes_photo_bridge.py lightroom-stage-latest
```
