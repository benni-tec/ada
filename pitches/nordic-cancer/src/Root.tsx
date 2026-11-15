import './style.css'

import { Composition } from 'remotion'

import { FPS, HEIGHT, WIDTH } from './frame'
import { Pitch, PITCH_FRAMES } from './Pitch'
import { CASES_FRAMES, CasesScene, TRIALS_FRAMES, TrialsScene } from './scenes/CasesScene'
import { CASES_DATA_FRAMES, CasesDataScene } from './scenes/CasesDataScene'
import { CHAT_FRAMES, ChatScene } from './scenes/ChatScene'

export const Root = () => (
  <>
    <Composition id="Pitch" component={Pitch} durationInFrames={PITCH_FRAMES} fps={FPS} width={WIDTH} height={HEIGHT} />
    {/* Each scene on its own, to work on it in the studio. */}
    <Composition id="Chat" component={ChatScene} durationInFrames={CHAT_FRAMES} fps={FPS} width={WIDTH} height={HEIGHT} />
    <Composition id="Cases" component={CasesScene} durationInFrames={CASES_FRAMES} fps={FPS} width={WIDTH} height={HEIGHT} />
    <Composition id="CasesData" component={CasesDataScene} durationInFrames={CASES_DATA_FRAMES} fps={FPS} width={WIDTH} height={HEIGHT} />
    <Composition id="Trials" component={TrialsScene} durationInFrames={TRIALS_FRAMES} fps={FPS} width={WIDTH} height={HEIGHT} />
  </>
)
