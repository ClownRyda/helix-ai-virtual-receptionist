# Zoiper Softphone Setup Guide

Quick setup for testing the PBX assistant with Zoiper on your LAN.

Replace `YOUR_SERVER_IP` and the sample passwords below with the values you configured in `asterisk/etc/asterisk/pjsip.conf`.

---

## 1. Install Zoiper

- **Desktop (Mac/Win/Linux):** [zoiper.com/en/voip-softphone/download/current](https://www.zoiper.com/en/voip-softphone/download/current)
- **Mobile (iOS/Android):** Search "Zoiper" in your app store

---

## 2. Create Account in Zoiper

Open Zoiper → **Settings** → **Accounts** → **Add Account** → **SIP**

### Extension 1001 (Operator — Softphone #1)

| Field | Value |
|---|---|
| Account Name | `PBX 1001` |
| Domain / Server | `YOUR_SERVER_IP` |
| Username | `1001` |
| Password | `CHANGE_ME_EXT_1001_PASSWORD` |
| Auth Username | `1001` |
| Port | `5060` |
| Transport | `UDP` |

### Extension 1002 (Sales — Softphone #2)

| Field | Value |
|---|---|
| Account Name | `PBX 1002` |
| Domain / Server | `YOUR_SERVER_IP` |
| Username | `1002` |
| Password | `CHANGE_ME_EXT_1002_PASSWORD` |
| Auth Username | `1002` |
| Port | `5060` |
| Transport | `UDP` |

### Extension 1003 (Support — optional 3rd phone)

| Field | Value |
|---|---|
| Account Name | `PBX 1003` |
| Domain / Server | `YOUR_SERVER_IP` |
| Username | `1003` |
| Password | `CHANGE_ME_EXT_1003_PASSWORD` |
| Auth Username | `1003` |
| Port | `5060` |
| Transport | `UDP` |

---

## 3. Codec Settings

In Zoiper → **Settings** → **Audio** → **Codecs**, make sure these are enabled (in order of preference):

1. **G.722** (wideband, best quality for LAN)
2. **PCMU (G.711 µ-law)**
3. **PCMA (G.711 A-law)**

Disable all video codecs — we don't need them.

---

## 4. Verify Registration

After saving the account, Zoiper should show a green checkmark or "Registered" next to the account name. If it shows red/failed:

- Confirm the server is running: `docker compose ps` (or check `asterisk -rx "pjsip show endpoints"`)
- Confirm you're on the same LAN/subnet as the PBX server
- Check firewall: `sudo ufw status` — port 5060/udp must be open
- Try restarting the account in Zoiper

---

## 5. Test Calls

### Extension-to-Extension
1. Register 1001 on one device, 1002 on another
2. From 1001, dial **1002** → the other device should ring
3. Answer and confirm two-way audio

### AI Attendant
1. From any registered extension, dial **9999**
2. You should hear the AI greeting: _"Thank you for calling... How can I help you?"_
3. Speak naturally — the AI will listen, transcribe, and respond
4. Test flows:
   - **"I'd like to schedule a callback"** → scheduling flow
   - **"Transfer me to sales"** → transfers to ext 1002
   - **"I need technical support"** → transfers to ext 1003

---

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| "Registration failed" | Check IP, username, password. Run `asterisk -rx "pjsip show endpoints"` on server |
| One-way audio | Ensure `direct_media=no` in pjsip.conf (already set). Check RTP ports open in firewall |
| No audio at all | Check RTP port range 10000-20000 is open. Try `tcpdump -i any udp port 5060` on server |
| AI doesn't respond | Check agent container is running: `docker compose logs agent`. Verify Ollama has the model: `ollama list` |
| AI greeting plays but doesn't hear you | Check ExternalMedia RTP ports 20000-20100 are open. Look at `docker compose logs agent` for RTP errors |
| Choppy audio | Normal on WiFi. Use wired connection if possible, or try a different codec |

---

## Quick Reference

| What | How |
|---|---|
| Server IP | `YOUR_SERVER_IP` |
| SIP Port | `5060/UDP` |
| Extensions | `1001` / `1002` / `1003` |
| Passwords | The values you set in `pjsip.conf` |
| AI Number | **9999** |
| Dashboard | `http://YOUR_SERVER_IP:3000` |
| Agent API | `http://YOUR_SERVER_IP:8000` |
