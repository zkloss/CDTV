import React from 'react';
import {AbsoluteFill,Audio,Composition,Easing,Img,Sequence,interpolate,registerRoot,staticFile,useCurrentFrame,useVideoConfig} from 'remotion';
import {PaperTitleCard} from './upstream/aifl/PaperTitleCard';
import {VisualThemeProvider} from './upstream/themes/visual-theme';
import {Graphic,illustrationFor} from './graphics';
import {InkPressFilm} from './InkPressFilm';
import {InkPressTexture} from './InkPressTextures';
type Scene={kind:string;title:string;subtitle:string;items:string[];caption:string;from:number;frames:number;src?:string;illustration?:string};
type Plan={fps:number;width:number;height:number;durationInFrames:number;title:string;scenes:Scene[];sound?:boolean;audio?:string;music?:string;theme?:string;colors?:Record<string,string>;narrationClips?:{src:string;from:number;frames:number}[]};
const font='"Microsoft YaHei","Segoe UI",sans-serif';
const clip=(f:number,a:number,b:number)=>interpolate(f,[a,b],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp',easing:Easing.bezier(.2,.75,.3,1)});
const words=(title:string)=>title.match(/.{1,5}/gu)?.map((text,i)=>({text,accent:i===1}))||[{text:title}];
function fitted(items:string[],width:number,height:number,start:number){let size=start;const units=(s:string)=>[...s].reduce((n,c)=>n+(/[\x00-\x7f]/.test(c)?.58:1),0);while(size>24&&items.reduce((n,s)=>n+Math.ceil(units(s)*size/Math.max(120,width-70))*size*1.5+36,0)+Math.max(0,items.length-1)*16>height)size-=2;return size}
const Panel:React.FC<{scene:Scene;colors:Record<string,string>;theme:string;index:number;total:number}>=({scene:s,colors:c,theme,index,total})=>{
 const f=useCurrentFrame();const {width,height}=useVideoConfig();const portrait=height>width;const pad=portrait?64:92;const enter=clip(f,0,13);const illustration=illustrationFor(s,theme);const art=!!illustration||!!s.src;const hero=['title','outro'].includes(s.kind)||(s.kind==='statement'&&!s.items.length);const items=s.items||[];
 const bodyHeight=height-pad*2-(s.subtitle?210:150)-(s.caption?80:0);const bodyWidth=(width-pad*2)*(art&&!portrait?.52:1);const size=fitted(items,bodyWidth,portrait?bodyHeight*.52:bodyHeight,art?38:46);
 if(theme==='paper'&&['title','outro'].includes(s.kind))return <AbsoluteFill><PaperTitleCard duration={s.frames+12} words={words(s.title)} sub={s.subtitle} fontSize={portrait?80:Math.max(66,Math.min(114,170-s.title.length*1.8))} {...c}/>{s.caption&&<div style={{position:'absolute',bottom:55,left:pad,right:pad,fontFamily:font,fontSize:29,color:c.muted,textAlign:'center'}}>{s.caption}</div>}</AbsoluteFill>;
 return <AbsoluteFill style={{background:c.paper,color:c.ink,fontFamily:font,padding:pad,overflow:'hidden'}}>
  <div style={{position:'absolute',inset:0,backgroundImage:`radial-gradient(ellipse at 92% 25%,${theme==='technology'?'#1e426970':'#a7c88a28'},transparent 62%)`,pointerEvents:'none'}}/>
  <div style={{display:'flex',alignItems:'center',gap:16,marginBottom:hero?32:25,color:c.muted,fontSize:21,letterSpacing:2}}><span style={{width:42,height:4,background:c.accent}}/>{String(index+1).padStart(2,'0')}<span style={{opacity:.6}}>/ {String(total).padStart(2,'0')}</span><span style={{marginLeft:'auto',fontSize:18}}>{illustration?'原理示意':''}</span></div>
  <div style={{flex:1,minHeight:0,display:'flex',flexDirection:portrait?'column':'row',gap:portrait?30:50,alignItems:'stretch'}}>
   <div style={{flex:art&&!portrait?'0 0 52%':'1',minWidth:0,display:'flex',flexDirection:'column',justifyContent:hero?'center':'flex-start',transform:`translateY(${18*(1-enter)}px)`}}>
    <h1 style={{fontSize:hero?(portrait?73:Math.max(62,Math.min(98,118-s.title.length*1.6))):(portrait?61:Math.max(48,74-s.title.length*.6)),fontWeight:700,lineHeight:1.28,margin:'0 0 25px',letterSpacing:-1.5,overflowWrap:'anywhere',textWrap:'balance'}}>{s.title}</h1>
    {s.subtitle&&<div style={{fontSize:portrait?32:36,lineHeight:1.7,color:c.muted,marginBottom:items.length?30:0}}>{s.subtitle}</div>}
    {items.length>0&&<div style={{display:'grid',gridTemplateColumns:s.kind==='comparison'&&!art&&!portrait?'1fr 1fr':'1fr',gap:16,flex:hero?undefined:1,alignContent:'center',minHeight:0}}>{items.map((item,i)=>{const t=clip(f,5+i*7,19+i*7);return <div key={i} style={{display:'flex',gap:18,alignItems:'center',padding:'15px 22px',borderRadius:16,background:c.card,border:'1px solid '+c.border,transform:`translateY(${15*(1-t)}px)`,opacity:.35+.65*t}}><span style={{fontSize:21,color:c.accent,flexShrink:0,fontWeight:700}}>{s.kind==='steps'?String(i+1).padStart(2,'0'):'•'}</span><div style={{fontSize:size,lineHeight:1.5,overflowWrap:'anywhere'}}>{item}</div></div>})}</div>}
    {hero&&!s.subtitle&&!items.length&&<div style={{width:105,height:5,background:c.accent,marginTop:15}}/>}
   </div>
   {art&&<div style={{flex:portrait?'0 1 46%':'1',minHeight:0,minWidth:0,display:'flex',alignItems:'center',justifyContent:'center',padding:portrait?10:15}}>{s.src?<Img src={staticFile(s.src)} style={{width:'100%',height:'100%',objectFit:'contain',borderRadius:22,transform:`scale(${1+.02*clip(f,0,s.frames)})`}}/>:<Graphic kind={illustration} colors={c} items={items}/>}</div>}
  </div>
  {s.caption&&<div style={{position:'relative',marginTop:22,padding:'16px 22px',borderLeft:'4px solid '+c.accent,background:c.card,fontSize:portrait?28:31,lineHeight:1.5,color:c.ink,borderRadius:'0 12px 12px 0'}}>{s.caption}</div>}
  <div style={{height:3,background:c.border,marginTop:24}}><div style={{height:'100%',background:c.accent,width:`${100*clip(f,0,s.frames-1)}%`}}/></div>
 </AbsoluteFill>
}
export const Film:React.FC<Plan>=(p)=>{
 if((p as any).templateId==='ink-press')return <InkPressFilm plan={p}/>;
 const theme=p.theme||(/光合作用|叶绿体|植物/.test(p.title)?'botanical':'editorial');const f=useCurrentFrame();
 const c:Record<string,string>=theme==='technology'?{paper:'#101e30',ink:'#eef5ff',accent:'#6dcbec',muted:'#b1c4da',card:'#1a2c42',border:'#30455c'}:theme==='botanical'?{paper:'#f1f6eb',ink:'#193c2d',accent:'#3e754a',muted:'#4c6856',card:'#ffffff',border:'#d5e3ce'}:{paper:'#f3f5fa',ink:'#1b2e49',accent:'#3b65a0',muted:'#546681',card:'#ffffff',border:'#d9e0ee'};
 if(theme==='paper')Object.assign(c,{paper:'#f9f6f1',ink:'#26352a',accent:'#59733e',muted:'#52604f'});Object.assign(c,p.colors||{});
 return <VisualThemeProvider theme="ink-press"><AbsoluteFill style={{background:c.paper,fontFamily:font}}>
  {p.scenes.map((s,i)=><Sequence key={i} from={s.from} durationInFrames={s.frames}><Panel scene={s} colors={c} theme={theme} index={i} total={p.scenes.length}/></Sequence>)}
  {p.sound&&p.scenes.map((s,i)=><Sequence key={'sfx-'+i} from={s.from} durationInFrames={Math.min(s.frames,30)}><Audio src={staticFile(i===p.scenes.length-1?'sparkle.mp3':i%2?'pop.mp3':'swoosh-quick.mp3')} volume={.075}/></Sequence>)}
  {p.audio&&<Audio src={staticFile(p.audio)} volume={1}/>}
  {p.narrationClips?.map((a,i)=><Sequence key={'voice-'+i} from={a.from} durationInFrames={a.frames}><Audio src={staticFile(a.src)} volume={1}/></Sequence>)}
  {p.music&&<Audio src={staticFile(p.music)} loop volume={.1*Math.min(clip(f,0,24),1-clip(f,p.durationInFrames-35,p.durationInFrames))}/>}
 </AbsoluteFill></VisualThemeProvider>
}
registerRoot(()=><><Composition id="CdtvWholeFilm" component={Film} width={1920} height={1080} fps={30} durationInFrames={900} defaultProps={{fps:30,width:1920,height:1080,durationInFrames:900,title:'',scenes:[]}} calculateMetadata={({props})=>({width:props.width,height:props.height,fps:props.fps,durationInFrames:props.durationInFrames})}/><Composition id="CdtvInkTexture" component={InkPressTexture} width={1920} height={1080} fps={30} durationInFrames={60} defaultProps={{plan:{scenes:[]},texture:{part:'nav',w:1920,h:1080}}} calculateMetadata={({props})=>({width:props.texture.w,height:props.texture.h})}/></>);
