/**
 * Hospital Directory Calling API (Node.js + Express + Twilio)
 *
 * Quick start:
 * 1) npm install express cors dotenv twilio
 * 2) Create a .env file in the same folder with:
 *      TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
 *      TWILIO_AUTH_TOKEN=your_auth_token_here
 *      TWILIO_PHONE_NUMBER=+1xxxxxxxxxx   (your Twilio number in E.164 format)
 * 3) node twilio-hospital-server.js
 * 4) Open: http://localhost:3000
 */

const path = require("path");
const express = require("express");
const cors = require("cors");
const dotenv = require("dotenv");
const twilio = require("twilio");

dotenv.config();

const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname)));

// ----- Twilio credentials -----
// Insert values in .env (recommended). Do not hardcode secrets in source code.
const ACCOUNT_SID = process.env.TWILIO_ACCOUNT_SID;
const AUTH_TOKEN = process.env.TWILIO_AUTH_TOKEN;
const TWILIO_PHONE_NUMBER = process.env.TWILIO_PHONE_NUMBER;

// Guard: validate Twilio credentials on boot.
if (!ACCOUNT_SID || !AUTH_TOKEN || !TWILIO_PHONE_NUMBER) {
  console.warn(
    "[WARN] Missing Twilio env vars. Please set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER in .env"
  );
}

const twilioClient = twilio(ACCOUNT_SID, AUTH_TOKEN);

// Hospital directory with your requested numbers.
// Twilio expects E.164, so +91 prefix is added for India numbers.
const hospitals = {
  "hospital-1": { name: "Hospital 1", phone: "+916305198595" },
  "hospital-2": { name: "Hospital 2", phone: "+917416099434" },
  "hospital-3": { name: "Hospital 3", phone: "+917670889575" },
  "hospital-4": { name: "Hospital 4", phone: "+919032210200" },
};

app.get("/api/hospitals", (req, res) => {
  res.json(Object.entries(hospitals).map(([id, data]) => ({ id, ...data })));
});

app.post("/api/call", async (req, res) => {
  try {
    if (!ACCOUNT_SID || !AUTH_TOKEN || !TWILIO_PHONE_NUMBER) {
      return res.status(500).json({
        success: false,
        error:
          "Twilio credentials missing. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER in .env.",
      });
    }

    const { hospitalId } = req.body;
    const hospital = hospitals[hospitalId];

    if (!hospital) {
      return res.status(400).json({
        success: false,
        error: "Invalid hospitalId.",
      });
    }

    // Create a voice call using inline TwiML.
    const call = await twilioClient.calls.create({
      to: hospital.phone,
      from: TWILIO_PHONE_NUMBER,
      twiml: `<Response><Say voice="alice">This is an automated emergency contact call from your hospital directory system.</Say></Response>`,
    });

    return res.json({
      success: true,
      hospital: hospital.name,
      to: hospital.phone,
      callSid: call.sid,
      status: call.status,
      message: `Call initiated to ${hospital.name}`,
    });
  } catch (error) {
    console.error("Twilio call error:", error.message);
    return res.status(500).json({
      success: false,
      error: error.message || "Failed to initiate call.",
    });
  }
});

// Serve the frontend page
app.get("/", (req, res) => {
  res.sendFile(path.join(__dirname, "twilio-hospital-ui.html"));
});

app.listen(PORT, () => {
  console.log(`Server running at http://localhost:${PORT}`);
});

