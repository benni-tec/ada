import './style.css'

import { Composition } from 'remotion'

import { FPS, HEIGHT, WIDTH } from './frame'
import { Pitch, PITCH_FRAMES } from './Pitch'
import { CASES_FRAMES, CasesScene } from './scenes/CasesScene'
import { CHAT_FRAMES, ChatScene } from './scenes/ChatScene'

export const Root = () => (
  <>
    <Composition id="Pitch" component={Pitch} durationInFrames={PITCH_FRAMES} fps={FPS} width={WIDTH} height={HEIGHT} />
    {/* Each scene on its own, to work on it in the studio. */}
    <Composition id="Chat" component={ChatScene} durationInFrames={CHAT_FRAMES} fps={FPS} width={WIDTH} height={HEIGHT} />
    <Composition id="Cases" component={CasesScene} durationInFrames={CASES_FRAMES} fps={FPS} width={WIDTH} height={HEIGHT} />
  </>
)
