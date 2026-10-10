"""Fixed customer-facing messages in English, Tamil and Hindi.

These are written by people, not generated: the opening question and above
all the safety warning must always contain the same guidance (policy POL-5.4),
and sending them costs no Gemini request.
"""

LANGUAGES = ["English", "Tamil", "Hindi"]

OPENING = {
    "English": (
        "Hello {name}. This is the ScamShield Bank safety assistant. We have paused your payment of "
        "₹{amount} to {payee} for a quick safety check. Your money is safe. Did you make this payment yourself?"
    ),
    "Tamil": (
        "வணக்கம் {name}. இது ScamShield வங்கியின் பாதுகாப்பு உதவியாளர். {payee} என்ற கணக்கிற்கு நீங்கள் அனுப்பிய "
        "₹{amount} பணப்பரிமாற்றத்தை ஒரு சிறிய பாதுகாப்புச் சரிபார்ப்புக்காக நிறுத்தி வைத்துள்ளோம். "
        "உங்கள் பணம் பாதுகாப்பாக உள்ளது. இந்தப் பணப்பரிமாற்றத்தை நீங்களே செய்தீர்களா?"
    ),
    "Hindi": (
        "नमस्ते {name}। यह ScamShield बैंक का सुरक्षा सहायक है। हमने {payee} को आपके ₹{amount} के भुगतान को "
        "एक छोटी सुरक्षा जाँच के लिए रोक दिया है। आपका पैसा सुरक्षित है। क्या यह भुगतान आपने स्वयं किया है?"
    ),
}

# Shown when the rule engine starts a safety pause. {signals} is a list of
# the scam signals found, in the customer's language.
SAFETY_WARNING = {
    "English": (
        "⚠ We have paused this payment for your safety. What you told us matches a known scam pattern: {signals}. "
        "Your money has not left your account.\n"
        "• Never share your OTP, PIN or password with anyone.\n"
        "• Banks, police and government agencies never ask you to transfer money or move it to a \"safe account\".\n"
        "• End the call with anyone who is pressuring you, and talk to someone you trust.\n"
        "• To report cyber fraud, call 1930 or visit cybercrime.gov.in.\n"
        "Our fraud team will review this and contact you. You can cancel the payment at any time."
    ),
    "Tamil": (
        "⚠ உங்கள் பாதுகாப்பிற்காக இந்தப் பணப்பரிமாற்றத்தை நிறுத்தி வைத்துள்ளோம். நீங்கள் கூறிய தகவல்கள் "
        "அறியப்பட்ட மோசடி முறையுடன் ஒத்துப்போகின்றன: {signals}. உங்கள் பணம் உங்கள் கணக்கிலேயே பாதுகாப்பாக உள்ளது.\n"
        "• உங்கள் OTP, PIN அல்லது கடவுச்சொல்லை யாரிடமும் பகிர வேண்டாம்.\n"
        "• வங்கிகள், காவல்துறை, அரசு அமைப்புகள் ஒருபோதும் பணம் அனுப்பச் சொல்லவோ \"பாதுகாப்பான கணக்கிற்கு\" "
        "மாற்றச் சொல்லவோ மாட்டார்கள்.\n"
        "• உங்களை அவசரப்படுத்தும் அல்லது மிரட்டும் நபரின் அழைப்பைத் துண்டியுங்கள்; நீங்கள் நம்பும் ஒருவரிடம் பேசுங்கள்.\n"
        "• சைபர் மோசடியைப் புகாரளிக்க 1930 என்ற எண்ணை அழையுங்கள் அல்லது cybercrime.gov.in தளத்தைப் பார்வையிடுங்கள்.\n"
        "எங்கள் மோசடி தடுப்புக் குழு இதைச் சரிபார்த்து உங்களைத் தொடர்புகொள்ளும். "
        "நீங்கள் எப்போது வேண்டுமானாலும் இந்தப் பணப்பரிமாற்றத்தை ரத்து செய்யலாம்."
    ),
    "Hindi": (
        "⚠ आपकी सुरक्षा के लिए हमने यह भुगतान रोक दिया है। आपने जो बताया वह धोखाधड़ी के एक जाने-पहचाने तरीके से "
        "मेल खाता है: {signals}। आपका पैसा आपके खाते में सुरक्षित है।\n"
        "• अपना OTP, PIN या पासवर्ड किसी के साथ साझा न करें।\n"
        "• बैंक, पुलिस और सरकारी एजेंसियाँ कभी भी पैसे भेजने या \"सुरक्षित खाते\" में डालने को नहीं कहतीं।\n"
        "• जो व्यक्ति आप पर दबाव डाल रहा है उसका कॉल काट दें और किसी भरोसेमंद व्यक्ति से बात करें।\n"
        "• साइबर धोखाधड़ी की शिकायत के लिए 1930 पर कॉल करें या cybercrime.gov.in पर जाएँ।\n"
        "हमारी धोखाधड़ी रोकथाम टीम इसकी समीक्षा करके आपसे संपर्क करेगी। आप किसी भी समय यह भुगतान रद्द कर सकते हैं।"
    ),
}

# Reply to anything the customer sends once the chat is closed.
CHAT_CLOSED = {
    "English": "This payment is on hold and our fraud team is reviewing it. They will contact you. If you are being pressured by anyone, call 1930.",
    "Tamil": "இந்தப் பணப்பரிமாற்றம் நிறுத்தி வைக்கப்பட்டுள்ளது; எங்கள் மோசடி தடுப்புக் குழு இதைச் சரிபார்க்கிறது. அவர்கள் உங்களைத் தொடர்புகொள்வார்கள். யாராவது உங்களை வற்புறுத்தினால் 1930 என்ற எண்ணை அழையுங்கள்.",
    "Hindi": "यह भुगतान रोका गया है और हमारी धोखाधड़ी रोकथाम टीम इसकी समीक्षा कर रही है। वे आपसे संपर्क करेंगे। यदि कोई आप पर दबाव डाल रहा है, तो 1930 पर कॉल करें।",
}

# Used when Gemini cannot be reached. The payment simply stays on hold.
ASSISTANT_UNAVAILABLE = {
    "English": "Sorry, I am having trouble replying right now. Your payment stays on hold and your money is safe. Our fraud team will review it and contact you.",
    "Tamil": "மன்னிக்கவும், இப்போது பதிலளிப்பதில் சிக்கல் உள்ளது. உங்கள் பணப்பரிமாற்றம் நிறுத்தி வைக்கப்பட்டுள்ளது; உங்கள் பணம் பாதுகாப்பாக உள்ளது. எங்கள் மோசடி தடுப்புக் குழு இதைச் சரிபார்த்து உங்களைத் தொடர்புகொள்ளும்.",
    "Hindi": "क्षमा करें, अभी उत्तर देने में समस्या आ रही है। आपका भुगतान रुका हुआ है और आपका पैसा सुरक्षित है। हमारी धोखाधड़ी रोकथाम टीम इसकी समीक्षा करके आपसे संपर्क करेगी।",
}

# Customer said they did not make the payment (possible account takeover).
PAYMENT_DENIED = {
    "English": "Thank you for telling us. This payment stays blocked and has been sent to our fraud team as a priority. Do not share any OTP or password with anyone who calls you.",
    "Tamil": "தெரிவித்ததற்கு நன்றி. இந்தப் பணப்பரிமாற்றம் தடுக்கப்பட்டுள்ளது; முன்னுரிமையுடன் எங்கள் மோசடி தடுப்புக் குழுவிற்கு அனுப்பப்பட்டுள்ளது. உங்களை அழைக்கும் யாரிடமும் OTP அல்லது கடவுச்சொல்லைப் பகிர வேண்டாம்.",
    "Hindi": "बताने के लिए धन्यवाद। यह भुगतान रोक दिया गया है और प्राथमिकता के साथ हमारी धोखाधड़ी रोकथाम टीम को भेजा गया है। कॉल करने वाले किसी भी व्यक्ति को OTP या पासवर्ड न बताएँ।",
}

# Scam signal types, with the label shown to customers and analysts.
SIGNAL_LABELS = {
    "third_party_on_call": {
        "English": "someone on a call is guiding the payment",
        "Tamil": "அழைப்பில் உள்ள ஒருவர் இந்தப் பணப்பரிமாற்றத்தை வழிநடத்துகிறார்",
        "Hindi": "कॉल पर कोई व्यक्ति भुगतान करवा रहा है",
    },
    "threat_of_arrest_or_freeze": {
        "English": "threats of arrest, legal action or account freeze",
        "Tamil": "கைது, சட்ட நடவடிக்கை அல்லது கணக்கு முடக்கம் என்ற மிரட்டல்",
        "Hindi": "गिरफ़्तारी, कानूनी कार्रवाई या खाता बंद करने की धमकी",
    },
    "fake_official": {
        "English": "someone claiming to be police, a government official or bank staff",
        "Tamil": "காவல்துறை, அரசு அதிகாரி அல்லது வங்கி ஊழியர் என்று கூறும் நபர்",
        "Hindi": "खुद को पुलिस, सरकारी अधिकारी या बैंक कर्मचारी बताने वाला व्यक्ति",
    },
    "urgency_pressure": {
        "English": "pressure to pay immediately",
        "Tamil": "உடனடியாகப் பணம் அனுப்ப வேண்டும் என்ற அழுத்தம்",
        "Hindi": "तुरंत भुगतान करने का दबाव",
    },
    "secrecy_demand": {
        "English": "being told to keep the payment secret",
        "Tamil": "இதை யாரிடமும் சொல்லக்கூடாது என்ற அறிவுறுத்தல்",
        "Hindi": "भुगतान को गुप्त रखने को कहा जाना",
    },
    "remote_access_app": {
        "English": "a request to install a screen-sharing or remote-access app",
        "Tamil": "திரை பகிர்வு அல்லது தொலைநிலை அணுகல் செயலியை நிறுவச் சொல்லுதல்",
        "Hindi": "स्क्रीन शेयरिंग या रिमोट एक्सेस ऐप इंस्टॉल करने को कहा जाना",
    },
    "promised_returns": {
        "English": "promised or guaranteed returns",
        "Tamil": "உறுதியான அல்லது அதிக லாபம் என்ற வாக்குறுதி",
        "Hindi": "पक्के या बहुत ज़्यादा मुनाफ़े का वादा",
    },
    "fee_to_release": {
        "English": "a fee demanded to release a prize, parcel, refund, loan or job",
        "Tamil": "பரிசு, பார்சல், பணத்திருப்பம், கடன் அல்லது வேலைக்காகக் கட்டணம் கேட்பது",
        "Hindi": "इनाम, पार्सल, रिफ़ंड, लोन या नौकरी के लिए शुल्क की माँग",
    },
    "otp_or_credential_request": {
        "English": "a request for an OTP, PIN, password or card details",
        "Tamil": "OTP, PIN, கடவுச்சொல் அல்லது அட்டை விவரங்களைக் கேட்பது",
        "Hindi": "OTP, PIN, पासवर्ड या कार्ड की जानकारी माँगना",
    },
    "suspicious_link": {
        "English": "a suspicious link or phone number in a message",
        "Tamil": "செய்தியில் சந்தேகத்திற்குரிய இணைப்பு அல்லது தொலைபேசி எண்",
        "Hindi": "संदेश में संदिग्ध लिंक या फ़ोन नंबर",
    },
    "safe_account_transfer": {
        "English": "being told to move money to a \"safe account\"",
        "Tamil": "\"பாதுகாப்பான கணக்கிற்கு\" பணத்தை மாற்றச் சொல்லுதல்",
        "Hindi": "पैसे को \"सुरक्षित खाते\" में भेजने को कहा जाना",
    },
    "embedded_instructions": {
        "English": "a message containing instructions aimed at the bank's system",
        "Tamil": "வங்கியின் அமைப்பை நோக்கிய கட்டளைகள் கொண்ட செய்தி",
        "Hindi": "बैंक के सिस्टम को निर्देश देने वाला संदेश",
    },
}
SIGNAL_TYPES = list(SIGNAL_LABELS)


def indian_amount(amount: float) -> str:
    """Whole rupees with Indian digit grouping: 180000 -> "1,80,000"."""
    digits = str(int(round(amount)))
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([head, *groups, tail])


def language_of(customer: dict | None) -> str:
    language = (customer or {}).get("preferred_language", "English")
    return language if language in LANGUAGES else "English"


def signal_list(signals: list[dict], language: str) -> str:
    """The signal labels, comma-separated, in the customer's language."""
    labels = [SIGNAL_LABELS.get(s["type"], {}).get(language, s["type"]) for s in signals]
    return ", ".join(dict.fromkeys(labels))
