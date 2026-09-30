CLEAN & CLEAR — listening demos
===============================

All comparisons are loudness-matched (-16 LUFS), so what you hear is
CLARITY, not volume.

clean-and-clear-demo.mp3      (v1)  raw Khmer TTS  ->  ffmpeg chain
clean-and-clear-demo-v2.mp3   (v2)  the same Khmer line three ways, labelled:
        "One. Raw text to speech."          the untouched edge-tts output
        "Two. Built-in ffmpeg clean-up."    spectral denoise + de-ess + EQ
                                            + 48 kHz + loudness master
        "Three. Neural Clean & Clear."      MossFormer2 neural denoise
                                            + the same master chain
      then a second Khmer line, raw / ffmpeg / neural again.

What to listen for
------------------
* RAW is quieter and softer — the master is what makes it "broadcast".
* The gap between the ffmpeg and the neural version is SMALL on plain TTS,
  because edge-tts already writes clean speech with digital-silence pauses.
  The neural engine earns its keep on:
    - RVC-converted audio (it removes the breathiness RVC adds),
    - real recordings (room, mic, hum),
    - long projects, where the little bits add up.
* v2 has no super-resolution (that needs more RAM than the test box had);
  on your PC, with `clearvoice` installed, Clean & Clear can also rebuild
  the 12-20 kHz band — that is the "air" you hear in commercial voices.

Bottom line: the ffmpeg chain is always available and already makes the
output sound finished; install clearvoice for the extra step.

KHMER VOICE COMPARISON  (added 2026-09-28)
==========================================

Two offline Khmer voices, same two sentences, same normalized text:

khmer-voice-a-standard.mp3    Meta MMS-TTS Khmer (the original model)
                              10.8 s of speech, median pitch 134 Hz — slower,
                              flatter, a bit robotic
khmer-voice-b-finetuned.mp3   the community fine-tune of the same model
                              8.6 s of speech, median pitch 200 Hz — a
                              different narrator, noticeably less drawn out

Both run with NO INTERNET (menu 7 -> option 2 installs them).

The whole point: the package is not tied to one cloud voice any more, and
neither of these can be taken away by a provider.

NARRATION STYLES  (build 2026-09-29i)
===================================

narration-styles.txt       the index: all FOURTEEN styles, timestamps and the
narration-styles.mp3       pause preset each one used.

The same Khmer passage in all 13 styles, in the order of the studio panel,
each segment announced by its own name in Khmer:

   1. Natural read            8. Meditation
   2. Documentary             9. Narrative Storytelling
   3. Movie trailer          10. Novel Narration
   4. Audiobook              11. Inner Monologue
   5. News anchor            12. Sad Romantic
   6. Explainer              13. Emotional Cinematic Storytelling
   7. Thriller

Same words in every segment — each style performs them its own way. Listen for:

  * pause length: meditation takes 1.4s of silence per gap, natural 0.1s (same
    passage, same words)
  * pace: meditation 0.81x, trailer 0.91x, news 1.06x — every style has its own
    pace from the STYLE_DELIVERY table, and your NARRATION SPEED applies on top
  * softness: meditation -1.2 dB sits softest; trailer +0.7 dB sits heaviest.
    Pitch stays 0.0 st in all 13 — the SPEAKER never changes, only the reading
  * narration-styles.txt lists pace, softness, pause and whispers per segment
  * Emotional Cinematic Storytelling (13): build l re-set it to the ORIGINAL
    voice — pace 0.99x at 0.0 dB, no tone shaping. What you hear is the
    storyteller READ: unhurried, phrase by phrase, sentences landing gently.
    A whisper is only ever a brief moment now, and only when the words earn
    it — never a whole narration (the sustained-whisper style was removed).
  * master: 48 kHz / 192 kbps mp3, -16 LUFS, same chain as Clean & Clear.

Rebuild it yourself (needs internet, the same edge voice the studio uses):

    cd pipeline
    python build_style_demo.py              # all 13
    python build_style_demo.py --only cinematic
    python build_style_demo.py --only cinematic

A single style on its own ships next to the full file:
`narration-styles-cinematic.mp3` — the Emotional Cinematic Storytelling
segment alone (label + the passage read the way that style reads it).

English equivalent: `all-13-narration-styles.mp3` at the top of the ZIP — the
13 panel clips (each style describing itself), back to back.
