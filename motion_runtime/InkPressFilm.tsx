import React from 'react';
import {AbsoluteFill,Audio,Sequence,staticFile} from 'remotion';
import {AIFL_SHOTS,SFX,sfxDuration} from './inkpress/aifl/Main';
import {SceneOpen} from './inkpress/aifl/live/SceneOpen';
import {SceneFlyIn} from './inkpress/aifl/live/SceneFlyIn';
import {SceneDetail} from './inkpress/aifl/live/SceneDetail';
import {ScenePapers} from './inkpress/aifl/live/ScenePapers';
import {SceneWbr} from './inkpress/aifl/live/SceneWbr';
import {SceneOutroLive} from './inkpress/aifl/live/SceneOutroLive';
import {PaperTitleCard} from './inkpress/aifl/PaperTitleCard';
import {Caption} from './inkpress/aifl/Caption';
import {FlashCut} from './inkpress/aifl/FlashCut';
import {VisualThemeProvider} from './inkpress/themes/visual-theme';
import {TemplateClock} from './inkpress/clock';
const slots=Object.keys(AIFL_SHOTS);
// Preserve original beat positions; make speech intelligible under native impacts.
const sfxGain=(p:any,frame:number)=>{
 if(p.audio)return .035;
 const gain=(p.narrationClips||[]).reduce((g:number,a:any)=>{const gap=Math.max(a.from-frame,frame-(a.from+a.frames-1),0);return Math.min(g,.1+.9*Math.min(1,gap/6))},1);
 return .35*gain;
};
const units=(s:string)=>[...s].reduce((n,c)=>n+(/[\x00-\x7f]/.test(c)?.55:1),0);
const fit=(s:string,max=112)=>Math.max(34,Math.min(max,1420/Math.max(1,units(s))));
const words=(s:string)=>{const chunk=Math.max(2,Math.ceil([...s].length/5));return [...s].reduce((a:string[],v,i)=>{if(i%chunk===0)a.push('');a[a.length-1]+=v;return a},[]).map((text,i)=>({text,accent:i===1}))};
export function InkPressFilm({plan:p}:{plan:any}){
 const source=p.scenes as any[];
 const scene=(s:any)=>{
  const slot=s.templateSlot;
  if(slot==='morning')return <SceneOpen wordmark={p.title} wordmarkSize={fit(p.title,104)} kicker={s.subtitle||'内容图解'} kickerSize={28} noteLine1={[...source[3].title].slice(0,7).join('')} noteLine2={[...source[3].title].slice(7,14).join('')} noteSize={20}/>;
  if(slot==='table')return <SceneFlyIn query={[...source[3].title].slice(0,7).join('')}/>;
  if(slot==='macro')return <SceneDetail/>;
  if(slot==='chart')return <ScenePapers title={s.title} subtitle={s.subtitle||'按过程逐项展开'} counterSize={76}/>;
  if(slot==='wbr')return <SceneWbr kicker={s.title} kickerSize={25} pastWeeks={source.slice(0,6).map((v,i)=>`${String(i+1).padStart(2,'0')}|内容回顾|${v.title}`).join('\n')}/>;
  if(slot==='outro')return <SceneOutroLive wordmark={s.title} wordmarkSize={fit(s.title,110)} tagline={s.subtitle||s.caption||'从内容理解过程'} taglineSize={28}/>;
  return <PaperTitleCard duration={s.frames} words={words(s.title)} fontSize={fit(s.title,100)} sub={s.subtitle}/>;
 };
 const nativeEvents=SFX.map(e=>{
  const index=slots.findIndex((k,i)=>e.from>=AIFL_SHOTS[k as keyof typeof AIFL_SHOTS].from&&(i===slots.length-1||e.from<AIFL_SHOTS[slots[i+1] as keyof typeof AIFL_SHOTS].from));
  const s=source[index],base=AIFL_SHOTS[slots[index] as keyof typeof AIFL_SHOTS];
  return {...e,from:s.from+e.from-base.from,duration:Math.min(sfxDuration(e),p.durationInFrames-(s.from+e.from-base.from))};
 });
 const ratio=p.width/p.height,scale=Math.min(p.width/1920,p.height/1080);
 return <VisualThemeProvider theme="ink-press"><AbsoluteFill style={{background:'#f2eee6'}}>
  <div style={{position:'absolute',width:1920,height:1080,left:(p.width-1920*scale)/2,top:(p.height-1080*scale)/2,transform:`scale(${scale})`,transformOrigin:'top left',overflow:'hidden'}}>
   {source.map((s,i)=><Sequence key={s.templateSlot} from={s.from} durationInFrames={s.frames} width={1920} height={1080}><AbsoluteFill data-template-scene={s.templateSlot}>
    {s.templateSlot.startsWith('card')?scene(s):<TemplateClock value={{native:s.nativeFrames,duration:s.frames,slot:s.templateSlot}}>{scene(s)}</TemplateClock>}
    {!s.templateSlot.startsWith('card')&&s.templateSlot!=='outro'&&(s.caption||s.narration)&&<Sequence from={Math.min(30,Math.floor(s.frames/5))} durationInFrames={Math.max(16,s.frames-Math.min(30,Math.floor(s.frames/5))-6)}><Caption text={s.caption||s.narration} duration={s.frames-Math.min(30,Math.floor(s.frames/5))-6} fontSize={27} bottom={34}/></Sequence>}
   </AbsoluteFill></Sequence>)}
   {source.filter(s=>['table','macro','chart','wbr'].includes(s.templateSlot)).map(s=><Sequence key={'flash-'+s.templateSlot} from={Math.max(0,s.from-5)} durationInFrames={10}><FlashCut duration={10}/></Sequence>)}
  </div>
  {p.sound&&nativeEvents.map((e,i)=><Sequence key={'sfx-'+i} from={e.from} durationInFrames={e.duration}><Audio src={staticFile('audio/'+e.src)} volume={f=>e.volume*sfxGain(p,e.from+f)}/></Sequence>)}
  {p.narrationClips?.map((a:any,i:number)=><Sequence key={'voice-'+i} from={a.from} durationInFrames={a.frames}><Audio src={staticFile(a.src)} volume={1}/></Sequence>)}
  {p.audio&&<Audio src={staticFile(p.audio)}/>}{p.music&&<Audio src={staticFile(p.music)} loop volume={.08}/>}
 </AbsoluteFill></VisualThemeProvider>;
}
