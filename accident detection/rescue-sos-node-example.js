/**
 * RescueLink — Node.js / Express SOS handler (REFERENCE)
 *
 * Runs FOUR Twilio actions concurrently via Promise.all for minimum latency.
 * Your production app should:
 *   - Authenticate the user (JWT / session)
 *   - Load bloodGroup + emergencyContact from your database
 *   - Validate coordinates
 *
 * Install: npm install twilio express dotenv
 * Env: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER (+1...)
 *      RESCUELINK_RESPONDER_SMS=comma,separated,E164
 *      RESCUELINK_RESPONDER_VOICE=+1...
 */

require("dotenv").config();
const express = require("express");
const twilio = require("twilio");

const app = express();
app.use(express.json());

const client = twilio(
  process.env.TWILIO_ACCOUNT_SID,
  process.env.TWILIO_AUTH_TOKEN
);
const FROM = process.env.TWILIO_PHONE_NUMBER;

function mapsUrl(lat, lng) {
  return `https://www.google.com/maps?q=${lat},${lng}`;
}

/**
 * Example controller — replace DB stub with real User.findById(req.user.id)
 */
app.post("/api/sos", async (req, res) => {
  try {
    const { latitude, longitude } = req.body;
    // const userId = req.user.id; // from auth middleware
    const user = {
      name: "Demo User",
      bloodGroup: "O+",
      emergencyContact: "+919876543210", // E.164
    };

    const lat = Number(latitude);
    const lng = Number(longitude);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
      return res.status(400).json({ error: "Invalid coordinates" });
    }

    const url = mapsUrl(lat, lng);
    const smsResponderBody = `EMERGENCY SOS: User requires immediate assistance. Blood Group: ${user.bloodGroup}. Location: ${url}`;
    const smsContactBody = `URGENT: ${user.name} has triggered an SOS. Their current location is: ${url}`;

    const voiceResponderTwiml = `<Response><Say voice="alice">Emergency SOS. ${user.name} requires immediate assistance. Blood group ${user.bloodGroup}. Check SMS for map link.</Say></Response>`;
    const voiceContactTwiml = `<Response><Say voice="alice">Alert: Your emergency contact has triggered an SOS. Please check your messages for their location.</Say></Response>`;

    const responderSmsTargets = (process.env.RESCUELINK_RESPONDER_SMS || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);

    const responderVoice = process.env.RESCUELINK_RESPONDER_VOICE;

    const actionA = Promise.all(
      responderSmsTargets.map((to) =>
        client.messages.create({ to, from: FROM, body: smsResponderBody })
      )
    ).then((msgs) => ({ action: "A", messageSids: msgs.map((m) => m.sid) }));

    const actionB = client.calls
      .create({
        to: responderVoice,
        from: FROM,
        twiml: voiceResponderTwiml,
      })
      .then((call) => ({ action: "B", callSid: call.sid }));

    const actionC = client.calls
      .create({
        to: user.emergencyContact,
        from: FROM,
        twiml: voiceContactTwiml,
      })
      .then((call) => ({ action: "C", callSid: call.sid }));

    const actionD = client.messages
      .create({
        to: user.emergencyContact,
        from: FROM,
        body: smsContactBody,
      })
      .then((msg) => ({ action: "D", messageSid: msg.sid }));

    const [a, b, c, d] = await Promise.all([actionA, actionB, actionC, actionD]);

    return res.json({ success: true, mapsUrl: url, results: { a, b, c, d } });
  } catch (err) {
    console.error(err);
    return res.status(500).json({ error: err.message });
  }
});

const PORT = process.env.PORT || 3001;
app.listen(PORT, () => console.log(`RescueLink SOS example on http://localhost:${PORT}`));
