---
name: voiceover-mastering
description: Clean up and master spoken-word audio (voiceover, podcast, narration, interview) in Audacity 4 through the audacity4 MCP tools, to a loudness target such as -16 LUFS / -1 dBTP. Use when the user asks to clean, level, de-noise, master or "make broadcast-ready" a voice recording.
---

# Voiceover mastering in Audacity 4

Works through the `audacity4` MCP server. Audacity 4 (the MCP-enabled build)
must be running; if the first call fails, run `audacity4-mcp doctor` in a
terminal and relay its output rather than guessing.

## Ground rules

- **Never touch the original file.** Import it, work in the project, export to
  new file names. Tell the user the output paths before exporting.
- **Measure before and after every stage that changes level.** Use
  `auto_analyze_audio` and report the numbers; do not claim a target was hit
  without a measurement that shows it.
- Every destructive effect is one undo step. If a stage makes things worse,
  `edit_undo` it and say so instead of stacking corrections on top.
- If a call times out with the "dialog needs a human" message, stop and ask the
  user to dismiss the dialog in Audacity; nothing else can clear it.

## Chain

Adjust to what the analysis shows. Skip stages it says are unnecessary.

1. **Import and measure**: `project_import_audio(path)`, then
   `auto_analyze_audio()`. Record peak, RMS, noise floor, clipping, DC offset.
2. **DC offset**: `effect_remove_dc_offset()` if the analysis reports any.
3. **Noise**: select a room-tone-only stretch with `select_region(start, end)`
   (the analysis lists silence gaps), `get_noise_profile()`, `select_all()`, then
   `noise_reduction(sensitivity=6, noise_gain_db=10-12)`. Stay gentle; artefacts
   are worse than hiss.
4. **Hum**: `effect_notch_filter(50 or 60)` only if hum is audible or measured.
5. **Tone**: there is no built-in high-pass wrapper in this build. Use an
   installed EQ (`suggest_and_add_effect(track_id, "eq")`, then
   `set_effect_parameters`) for an ~80 Hz high-pass and any presence lift, or
   `bass_and_treble` for simple shaping. Skip this stage if it isn't needed.
6. **De-ess**: `suggest_and_add_effect(track_id, "deesser")` if sibilance is a
   problem and a de-esser plugin is installed.
7. **Even out line-to-line level**: `compressor(threshold_db≈-20, ratio 3-4,
   attack 5-10 ms, release 100-200 ms)`. Re-measure RMS spread.
8. **Loudness**: `loudness_normalize(lufs_level=<target>)` - default -16 LUFS
   for podcasts/voiceover, -19 for mono distribution, ACX uses
   `auto_audiobook_mastering` instead. Check it did not push peaks over.
9. **True-peak ceiling**: `limiter(threshold_db=-1.0, ...)` for a -1 dBTP target,
   then measure once more.
10. **Export**: `project_export_audio(path)`. Note the bridge's export is a
    44.1 kHz WAV; if the user needs 24-bit/48 kHz or MP3, say so and convert
    the export with ffmpeg (`-c:a pcm_s24le -ar 48000`, or
    `-c:a libmp3lame -b:a 320k`) rather than claiming the bridge did it.

For a quick result instead of a hand-tuned chain, `auto_cleanup_podcast`,
`auto_cleanup_vocal` and `auto_cleanup_interview` run steps 2-8 in one call.

## Report back

A before/after table (integrated LUFS, true peak, RMS spread, noise floor),
which stages ran with what settings, anything skipped and why, and the output
paths.
