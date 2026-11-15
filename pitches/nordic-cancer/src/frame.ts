export const FPS = 30
export const WIDTH = 1920
export const HEIGHT = 1080

/** Seconds to frames. */
export const s = (seconds: number) => Math.round(seconds * FPS)
