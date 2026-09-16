/**
 * Which system APIs this build is allowed to touch.
 *
 * The first release of this app blacked out the screen and froze the whole
 * watch - no taps, no system gestures - and reading the code did not find the
 * cause. So the app is put back on the device one capability at a time, and
 * this constant is the only thing that changes between those builds. If a
 * build misbehaves, whatever it added is the culprit.
 *
 *   1  render only, no @system.* is ever required or called
 *   2  + @system.storage
 *   3  + @system.interconnect
 *
 * `require('@system.x')` is deliberately lazy, inside the wrappers, so a stage
 * that is not reached never resolves the module at all. The working reference
 * apps do the same. Note that manifest.features must still list every module
 * mentioned anywhere in the code: the toolkit throws on a missing feature.
 *
 * See docs/VELA-RULES.md.
 */

export const STAGE = 2

export const STAGE_STORAGE = 2
export const STAGE_INTERCONNECT = 3

/** Shown on the debug screen so the watch can tell us which build it runs. */
export const BUILD = 's2'

export function allows(stage) {
  return STAGE >= stage
}
