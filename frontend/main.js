// Jarvis V2 — Frontend
const orb = document.getElementById('orb');
const status = document.getElementById('status');
const transcript = document.getElementById('transcript');

let ws;
let audioQueue = [];
let isPlaying = false;
let audioUnlocked = false;

// Unlock audio on ANY user interaction
function unlockAudio() {
    if (!audioUnlocked) {
        const silent = new Audio('data:audio/mp3;base64,SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjU4Ljc2LjEwMAAAAAAAAAAAAAAA//tQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAWGluZwAAAA8AAAACAAABhgC7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7//////////////////////////////////////////////////////////////////8AAAAATGF2YzU4LjEzAAAAAAAAAAAAAAAAJAAAAAAAAAAAAYZNIGPkAAAAAAAAAAAAAAAAAAAA//tQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAWGluZwAAAA8AAAACAAABhgC7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7//////////////////////////////////////////////////////////////////8AAAAATGF2YzU4LjEzAAAAAAAAAAAAAAAAJAAAAAAAAAAAAYZNIGPkAAAAAAAAAAAAAAAAAAAA');
        silent.play().then(() => {
            audioUnlocked = true;
            console.log('[jarvis] Audio unlocked');
        }).catch(() => {});
    }
}
document.addEventListener('click', unlockAudio, { once: false });
document.addEventListener('touchstart', unlockAudio, { once: false });
document.addEventListener('keydown', unlockAudio, { once: false });

function connect() {
    ws = new WebSocket(`ws://${location.host}/ws`);
    ws.onopen = () => {
        console.log('[jarvis] WebSocket connected');
        status.textContent = 'Click anywhere once so Jarvis can speak.';
        setOrbState('thinking');
        // The server greets on connect; nothing to send here
    };
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'response') {
            addTranscript('jarvis', data.text);
            if (data.audio && data.audio.length > 0) {
                queueAudio(data.audio);
            } else if (data.speak) {
                // No ElevenLabs audio (e.g. out of credits): read it with the browser's built-in voice
                queueSpeech(data.speak);
            } else if (!isPlaying) {
                setOrbState(paused ? 'idle' : 'listening');
                startListening();
            }
        } else if (data.type === 'status') {
            status.textContent = data.text;
        }
    };
    ws.onclose = () => {
        status.textContent = 'Connection lost... reconnecting.';
        setTimeout(connect, 3000);
    };
}

function queueAudio(base64Audio) {
    audioQueue.push({ audio: base64Audio });
    if (!isPlaying) playNext();
}

function queueSpeech(text) {
    audioQueue.push({ speech: text });
    if (!isPlaying) playNext();
}

// Fallback voice: Edge's built-in voices, preferring ones close to the ElevenLabs "Brian" voice
// (warm, clear, American male). Voices load asynchronously, so pick lazily.
const FALLBACK_VOICES = [
    'Microsoft Brian Online (Natural)', 'Microsoft Andrew Online (Natural)',
    'Microsoft Guy Online (Natural)', 'Microsoft Christopher Online (Natural)',
    'Microsoft Eric Online (Natural)', 'Microsoft David',
];
let fallbackVoice = null;
function pickFallbackVoice() {
    const voices = window.speechSynthesis ? speechSynthesis.getVoices() : [];
    for (const name of FALLBACK_VOICES) {
        const v = voices.find(v => v.name.startsWith(name));
        if (v) return v;
    }
    return voices.find(v => v.lang === 'en-US') || voices.find(v => v.lang.startsWith('en')) || null;
}
if (window.speechSynthesis) {
    speechSynthesis.onvoiceschanged = () => { fallbackVoice = pickFallbackVoice(); };
}

// Speak with the fallback voice; calls done() exactly once when finished (or if it never reports finishing)
function speakWithBrowserVoice(text, done) {
    if (!window.speechSynthesis) { done(); return; }
    fallbackVoice = fallbackVoice || pickFallbackVoice();
    const utterance = new SpeechSynthesisUtterance(text);
    if (fallbackVoice) utterance.voice = fallbackVoice;
    utterance.lang = fallbackVoice ? fallbackVoice.lang : 'en-US';
    let finished = false;
    const startedAt = Date.now();
    const finish = (how) => {
        if (finished) return;
        finished = true;
        clearTimeout(guard);
        reportError(`fallback voice "${fallbackVoice ? fallbackVoice.name : 'default'}" ${how} after ${Date.now() - startedAt} ms`, false);
        done();
    };
    // Roughly 12 characters per second of speech, plus slack, in case 'end' never fires
    const guard = setTimeout(() => { speechSynthesis.cancel(); finish('timed out'); }, (text.length / 12 + 8) * 1000);
    utterance.onend = () => finish('finished');
    utterance.onerror = (e) => finish(`failed (${e.error})`);
    speechSynthesis.speak(utterance);
}

let currentAudio = null;  // keep a reference so the element can't be garbage-collected mid-playback
let audioGuard = null;    // fallback timer in case 'ended' never fires, which would leave the mic off

function playNext() {
    clearTimeout(audioGuard);
    if (audioQueue.length === 0) {
        isPlaying = false;
        currentAudio = null;
        setOrbState(paused ? 'idle' : 'listening');
        status.textContent = paused ? 'Paused. Click the orb to resume.' : '';
        startListening();
        return;
    }
    isPlaying = true;
    setOrbState('speaking');
    status.textContent = '';
    // Mute recognition while Jarvis talks so it doesn't hear itself
    if (isListening) recognition.abort();

    const item = audioQueue.shift();
    if (item.speech) {
        speakWithBrowserVoice(item.speech, playNext);
        return;
    }
    const b64 = item.audio;
    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
    const blob = new Blob([bytes], { type: 'audio/mpeg' });
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    currentAudio = audio;
    let finished = false;
    const finish = () => {
        if (finished) return;
        finished = true;
        URL.revokeObjectURL(url);
        playNext();
    };
    audio.onended = finish;
    audio.onerror = finish;
    audio.onloadedmetadata = () => {
        const seconds = isFinite(audio.duration) ? audio.duration : 30;
        clearTimeout(audioGuard);
        audioGuard = setTimeout(finish, (seconds + 3) * 1000);
    };
    audioGuard = setTimeout(finish, 60000);  // metadata never loaded
    audio.play().catch(err => {
        console.warn('[jarvis] Autoplay blocked, waiting for click...');
        status.textContent = 'Click anywhere so Jarvis can speak.';
        setOrbState('idle');
        // Wait for click then retry
        document.addEventListener('click', function retry() {
            document.removeEventListener('click', retry);
            audio.play().then(() => {
                setOrbState('speaking');
                status.textContent = '';
            }).catch(() => playNext());
        });
    });
}

// Wake words: only speech addressed to Jarvis is acted on, as "Jarvis ..." or "Hey J ...".
// It must come first, optionally after up to two filler words ("um, okay Jarvis"), so "I told Jarvis..."
// in a conversation doesn't count. Speech recognition often misspells the name, so close spellings
// count too ("Judges" was seen in the log for "Jarvis").
const WAKE_FILLERS = "hey|hi|hello|ok|okay|so|um|uh|er|ah|oh|yo|and|well|please";
const WAKE_NAMES = "jarvis|jarvis's|jervis|javis|jarvus|jarviss|jarves|jarvice|jarvys|jarbis|garvis|charvis|judges";
// "Hey J" as the recognizer tends to write it: "Hey J", "Hey J.", "Hey Jay", "AJ", "A. J.", and
// "Hey Jake" (Edge's most common mishearing in testing). A bare "J"/"Jay"/"Jake" doesn't count, so
// "Jay said..." in a conversation won't trigger it.
const HEY_J = "(?:hey|hay|hi|a)[\\s,.-]*(?:j|jay|jae|jey|jaye|jake|jk)\\.?|aj|heyjay|heyj";
const WAKE_WORD = new RegExp(
    `^\\s*(?:(?:${WAKE_FILLERS})[\\s,.!?]+){0,2}(?:${WAKE_NAMES}|${HEY_J})(?![\\w'])[\\s,.!?:;-]*`, "i");
// Mishearings only accepted when they're the entire phrase (the user said the wake word and paused):
// "Hey J." alone came out as "DJ." in testing, but "the DJ played..." must not trigger.
const BARE_WAKE = /^\s*(?:dj|d\.\s*j|deejay)[\s.!?]*$/i;
const WAKE_WINDOW_MS = 8000;
let wakeUntil = 0;  // after a bare "Jarvis", the next phrase within this window is accepted as the command
// Write every finished phrase (heard, and whether it was accepted) to jarvis.log to diagnose recognition.
// The log stays on this computer; set to false to stop logging background speech.
const LOG_HEARD = true;
// Diagnostics: log recognition session starts/ends and speech timing to jarvis.log
const LOG_SESSIONS = false;
let lastSessionEndedAt = 0;

// The command after the wake word ('' for a bare "Jarvis"), or null if the phrase isn't addressed to Jarvis.
// Background noise can get transcribed and glued in front of what the user said ("What's up there?
// Jarvis, what time is it?"), so the wake word may also start any sentence within the phrase.
function matchWakeWord(transcript) {
    if (BARE_WAKE.test(transcript)) return '';
    const sentences = transcript.split(/(?<=[.!?])\s+/);
    for (let i = 0; i < sentences.length; i++) {
        const fromHere = sentences.slice(i).join(' ');
        const match = fromHere.match(WAKE_WORD);
        if (match) return fromHere.slice(match[0].length).trim();
    }
    return null;
}

// Decide what a finished phrase means, checking all of the recognizer's alternative guesses
// ("Jarvis" is often the 2nd or 3rd guess when the top one is "Travis" or similar).
// Returns { command, heard }: command is the text to send, '' for a bare wake word, or null to ignore.
function extractCommand(alternatives) {
    for (const alt of alternatives) {
        const rest = matchWakeWord(alt);
        if (rest !== null) {
            wakeUntil = rest ? 0 : Date.now() + WAKE_WINDOW_MS;
            return { command: rest, heard: alt };
        }
    }
    if (Date.now() < wakeUntil) {
        wakeUntil = 0;
        return { command: alternatives[0], heard: alternatives[0] };
    }
    return { command: null, heard: alternatives[0] };
}

// Speech Recognition
// The microphone stays on whenever Jarvis isn't talking, until the user pauses (orb click) or closes Jarvis.
// Browsers end recognition sessions on their own (silence, network hiccups) and Edge sometimes lets a
// session go quiet without any event, so sessions are restarted as soon as they end and a watchdog
// checks the state every couple of seconds.
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const WATCHDOG_INTERVAL_MS = 2000;
const RECYCLE_SESSION_MS = 60000;   // refresh long sessions so a silently-dead one can't last long
const MIN_RESTART_GAP_MS = 1000;    // don't hammer start() if sessions end instantly (e.g. mic error)
let recognition;
let isListening = false;
let paused = false;
let userSpeaking = false;
let sessionStartedAt = 0;
let lastStartAttempt = 0;
let restartTimer = null;
let abortRequestedAt = 0;

function wantListening() {
    return recognition && !paused && !isPlaying;
}

if (SpeechRecognition) {
    recognition = new SpeechRecognition();
    recognition.lang = 'en-US';
    recognition.continuous = true;
    // Interim (in-progress) results are needed because Edge often DROPS the wake word from the final
    // text: after "Jarvis," or "Hey J." with a small pause it treats the name as its own tiny phrase and
    // discards it, delivering only "What is the capital of Spain?". The name does show up in the live
    // transcript while it's being spoken, so seeing it there arms Jarvis for the next finished phrase.
    recognition.interimResults = true;
    recognition.maxAlternatives = 5;

    // One event can carry several newly finished phrases (e.g. "Jarvis" + pause + "open YouTube"),
    // so handle every result from resultIndex on, not just the last one.
    recognition.onresult = (event) => {
        for (let i = event.resultIndex; i < event.results.length; i++) {
            const result = event.results[i];
            const alternatives = Array.from(result).map(a => a.transcript.trim()).filter(Boolean);
            if (!alternatives.length) continue;
            if (result.isFinal) {
                handlePhrase(alternatives, result[0].confidence);
            } else {
                handleInterim(alternatives[0]);
            }
        }
    };

    recognition.onstart = () => {
        isListening = true;
        userSpeaking = false;
        sessionStartedAt = Date.now();
        if (LOG_SESSIONS) reportError(`session start (${lastSessionEndedAt ? Date.now() - lastSessionEndedAt : '-'} ms after last end)`, false);
        if (!isPlaying) {
            setOrbState('listening');
            status.textContent = 'Listening...';
        }
    };

    recognition.onspeechstart = () => {
        userSpeaking = true;
        if (LOG_SESSIONS) reportError(`speech start (${Date.now() - sessionStartedAt} ms into session)`, false);
    };
    recognition.onspeechend = () => { userSpeaking = false; };

    // The only place a session is restarted after it ends: immediately, not via a (throttleable) timer,
    // unless the last start was very recent, which means sessions are failing instantly.
    recognition.onend = () => {
        isListening = false;
        userSpeaking = false;
        abortRequestedAt = 0;
        lastSessionEndedAt = Date.now();
        if (LOG_SESSIONS) reportError(`session end after ${Date.now() - sessionStartedAt} ms${isPlaying ? ' (Jarvis speaking)' : ''}`, false);
        if (!wantListening()) return;
        const sinceStart = Date.now() - lastStartAttempt;
        if (sinceStart >= MIN_RESTART_GAP_MS) {
            startListening();
        } else {
            clearTimeout(restartTimer);
            restartTimer = setTimeout(startListening, MIN_RESTART_GAP_MS - sinceStart);
        }
    };

    recognition.onerror = (event) => {
        // 'no-speech' and 'aborted' are routine; onend follows every error and restarts the session
        if (LOG_SESSIONS) reportError(`session error: ${event.error}`, false);
        if (event.error === 'no-speech' || event.error === 'aborted') return;
        const hints = {
            'not-allowed': 'Microphone blocked. Allow the microphone for this window, then click the orb.',
            'audio-capture': 'No microphone found. Check your input device in Windows sound settings.',
            'network': 'Speech service hiccup. Reconnecting...',
            'service-not-allowed': 'Speech recognition is disabled in this browser.',
        };
        status.textContent = hints[event.error] || `Speech recognition error: ${event.error}. Retrying...`;
        reportError(`recognition error: ${event.error}`);
    };

    // Watchdog: restart if listening should be on but isn't, and refresh long sessions
    // (never while the user is mid-sentence) so one that silently stopped can't stay dead.
    setInterval(() => {
        if (!wantListening()) return;
        const now = Date.now();
        if (!isListening && now - lastStartAttempt > 3000) {
            reportError('watchdog: recognition was off, restarting');
            startListening();
        } else if (isListening && abortRequestedAt && now - abortRequestedAt > 3000) {
            // abort() never produced an 'end' event: the session is wedged, so start a fresh one
            reportError('watchdog: recognition session stuck, forcing restart');
            abortRequestedAt = 0;
            isListening = false;
            startListening();
        } else if (isListening && !userSpeaking && now - sessionStartedAt > RECYCLE_SESSION_MS && !abortRequestedAt) {
            abortRequestedAt = now;
            recognition.abort();  // onend restarts it straight away
        }
    }, WATCHDOG_INTERVAL_MS);
} else {
    status.textContent = 'This browser has no speech recognition. Open this page in Google Chrome.';
    reportError('SpeechRecognition API not available');
}

// Live transcript while the user is still speaking: if it starts with the wake word, arm Jarvis so the
// finished phrase is accepted even if Edge drops the name from it.
function handleInterim(text) {
    if (matchWakeWord(text) === null) return;
    const wasArmed = Date.now() < wakeUntil;
    wakeUntil = Date.now() + WAKE_WINDOW_MS;
    if (!wasArmed) {
        status.textContent = 'Yes? Listening for your command...';
        if (LOG_HEARD) reportError(`heard wake word (live): "${text}"`, false);
    }
}

function handlePhrase(alternatives, confidence) {
    const { command, heard } = extractCommand(alternatives);
    if (LOG_HEARD) {
        const verdict = command === null ? 'IGNORED' : command === '' ? 'WAKE WORD ONLY' : 'ACCEPTED';
        const conf = typeof confidence === 'number' ? ` conf=${confidence.toFixed(2)}` : '';
        reportError(`heard ${verdict}${conf}: ${alternatives.map(a => `"${a}"`).join(' / ')}`, false);
    }
    if (command === null) {
        status.textContent = `Heard: "${heard}" (ignored: start with "Jarvis" or "Hey J")`;
        return;
    }
    if (command === '') {
        status.textContent = 'Yes? Listening for your command...';
        return;
    }
    addTranscript('user', heard);
    setOrbState('thinking');
    status.textContent = 'Jarvis is thinking...';
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ text: command }));
    } else {
        status.textContent = 'Not connected to the Jarvis server. Reconnecting...';
    }
}

function reportError(message, withBrowser = true) {
    console.warn('[jarvis]', message);
    const stamp = new Date().toTimeString().slice(0, 8);
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ log: `${stamp} ${message}${withBrowser ? ` | ${navigator.userAgent}` : ''}` }));
    }
}

function startListening() {
    clearTimeout(restartTimer);
    if (!wantListening() || isListening) return;
    lastStartAttempt = Date.now();
    try {
        recognition.start();
    } catch(e) {
        // start() throws InvalidStateError if a session is still running or winding down;
        // its onend (or the watchdog) will start the next one
        if (e.name !== 'InvalidStateError') reportError(`recognition.start failed: ${e.message}`);
    }
}

// Clicking the orb pauses/resumes listening; otherwise the microphone stays on while Jarvis is open
orb.addEventListener('click', () => {
    if (isPlaying) return;
    paused = !paused;
    if (paused) {
        if (isListening) recognition.abort();
        setOrbState('idle');
        status.textContent = 'Paused. Click the orb to resume.';
    } else {
        status.textContent = 'Listening...';
        startListening();
    }
});

function setOrbState(state) { orb.className = state; }

function addTranscript(role, text) {
    const div = document.createElement('div');
    div.className = role;
    div.textContent = role === 'user' ? `You: ${text}` : `Jarvis: ${text}`;
    transcript.appendChild(div);
    transcript.scrollTop = transcript.scrollHeight;
}

connect();
