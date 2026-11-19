import React from 'react';
import {AbsoluteFill,Img,staticFile} from 'remotion';
import layout from './inkpress/aifl/live-layout.json';
import {Graphic,illustrationFor} from './graphics';
const c={paper:'#faf7f2',ink:'#13110f',accent:'#955905',muted:'#65635f',card:'#fff',border:'#dfdfd3'};
const font='"Microsoft YaHei","Segoe UI",sans-serif';
const pos=(r:any)=>({position:'absolute' as const,left:r.x,top:r.y,width:r.w,height:r.h,boxSizing:'border-box' as const});
export function textureTasks(){
 const tasks:any[]=[['projects-full.png',1920,layout.projects.pageH,'projects'],['projects-empty.png',1920,layout.projects.pageH,'empty'],['detail-full.png',1920,layout.detail.pageH,'detail'],['papers-full.png',1920,layout.papers.pageH,'papers'],['wbr-full.png',1920,layout.wbr.pageH,'wbr']].map(([file,w,h,part])=>({file,w,h,part,scale:2}));
 layout.projects.cards.forEach((r,i)=>tasks.push({file:r.file,w:Math.ceil(r.w),h:Math.ceil(r.h),part:'tile',index:i,scale:2}));
 tasks.push({file:'card4-hires.png',w:Math.ceil(layout.projects.cards[3].w),h:Math.ceil(layout.projects.cards[3].h),part:'tile',index:3,scale:4});
 layout.papers.cards.forEach((r,i)=>tasks.push({file:`paper${i+1}.png`,w:Math.ceil(r.w),h:Math.ceil(r.h),part:'paper',index:i,scale:2}));
 layout.float.forEach((r,i)=>tasks.push({file:r.file,w:Math.ceil(r.w),h:Math.ceil(r.h),part:'float',index:i,scale:2}));
 tasks.push({file:'nav.png',w:1920,h:61,part:'nav',scale:2});return tasks;
}
function Artwork({s,p}:{s:any;p:any}){
 const botanical=/光合作用|叶绿|植物|类囊体/.test(JSON.stringify(p.scenes));
 const illustration=illustrationFor(s,botanical?'botanical':'editorial');
 return s.src?<Img src={staticFile(s.src)} style={{width:'100%',height:'100%',objectFit:'contain'}}/>:illustration?<Graphic kind={illustration} colors={c} items={s.items||[]}/>:<div style={{display:'grid',placeItems:'center',width:'100%',height:'100%',background:'#edf1e7',borderRadius:16,fontSize:32,fontWeight:700,textAlign:'center',padding:20,boxSizing:'border-box'}}>{s.title}</div>;
}
function Tile({s,p}:{s:any;p:any}){return <AbsoluteFill style={{background:'#fff',border:'1px solid #d8dfd0',borderRadius:16,padding:16,color:c.ink,fontFamily:font,overflow:'hidden'}}><div style={{fontSize:20,fontWeight:700,lineHeight:1.45}}>{s.title}</div><div style={{position:'absolute',left:36,right:36,top:58,bottom:42}}><Artwork s={s} p={p}/></div><div style={{position:'absolute',left:16,right:16,bottom:15,fontSize:15,color:c.muted,whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}}>{s.subtitle||s.narration||s.caption||'内容图解 · 原理示意'}</div></AbsoluteFill>}
const unique=(values:any[])=>[...new Set(values.filter(v=>typeof v==='string'&&v.trim()).map(v=>v.trim()))];
const points=(s:any)=>unique([...(s.items||[]),s.narration,s.title,s.subtitle,...(s.details||[])]);
const source=(p:any,i:number)=>p.scenes[Math.min(i===8?3:i,p.scenes.length-1)];
function Nav({p}:{p:any}){return <AbsoluteFill style={{background:'#faf7f2',borderBottom:'1px solid #dedecf',display:'flex',flexDirection:'row',alignItems:'center',gap:45,padding:'0 65px',fontSize:22}}><b>{p.title}</b><span style={{marginLeft:'auto'}}>内容图解</span><span>过程</span><span>总结</span></AbsoluteFill>}
function Search({p}:{p:any}){return <AbsoluteFill style={{background:'#fff',border:'1px solid #d8dfd0',borderRadius:10,padding:'6px 18px',color:c.muted,fontSize:22}}>⌕　{source(p,2).title}</AbsoluteFill>}
function Paper({p,index}:{p:any;index:number}){const s=source(p,5),items=points(s);return <AbsoluteFill style={{background:'#fff',border:'1px solid #d8dfd0',borderRadius:12,padding:'24px 32px',display:'flex',flexDirection:'row',gap:24}}><div style={{width:140,flexShrink:0}}><Artwork s={{...s,illustration:index%2?'cycle':s.illustration}} p={p}/></div><div><div style={{fontSize:21,color:c.accent}}>过程 {String(index+1).padStart(2,'0')}</div><h2 style={{fontSize:29,margin:'14px 0'}}>{items[index]||''}</h2><p style={{fontSize:21,color:c.muted}}>{s.subtitle||s.narration||'循着变化，理解每一步'}</p></div></AbsoluteFill>}
function Float({p,index}:{p:any;index:number}){return index===1?<Search p={p}/>:<AbsoluteFill style={{background:'#fff',border:'1px solid #d8dfd0',borderRadius:8,padding:5,fontSize:index===3?25:18,color:c.muted}}>{index===0?'⌕':index===2?'内容与过程':source(p,2).title}</AbsoluteFill>}
export function InkPressTexture({plan:p,texture:t}:{plan:any;texture:any}){
 const render=()=>{
  if(t.part==='nav')return <Nav p={p}/>;
  if(t.part==='tile')return <Tile s={source(p,t.index)} p={p}/>;
  if(t.part==='paper')return <Paper p={p} index={t.index}/>;
  if(t.part==='float')return <Float p={p} index={t.index}/>;
  if(t.part==='projects'||t.part==='empty')return <><div style={{...pos({x:0,y:0,w:1920,h:61})}}><Nav p={p}/></div><div style={{...pos({x:70,y:145,w:270,h:1250}),borderRight:'1px solid #e0dfd0',fontSize:24,lineHeight:2.8,color:c.muted}}>内容导航<br/>概览<br/>原理<br/>变化<br/>总结</div><div style={pos({x:408,y:130,w:1016,h:44})}><Search p={p}/></div><div style={{...pos({x:408,y:199,w:1104,h:34}),fontSize:23,fontWeight:700}}>从内容，看见过程　<span style={{fontWeight:400,fontSize:18,color:c.muted}}>· 图解示意</span></div>{layout.projects.cards.map((r,i)=><div key={i} style={pos(r)}>{t.part==='projects'?<Tile s={source(p,i)} p={p}/>:null}</div>)}</>;
  if(t.part==='detail'){const s=source(p,3),rows=points(s);return <><div style={pos({x:0,y:0,w:1920,h:61})}><Nav p={p}/></div><div style={{...pos({x:408,y:130,w:1104,h:485}),display:'flex',gap:40,alignItems:'center'}}><div style={{width:500}}><h1 style={{fontSize:46,lineHeight:1.4}}>{s.title}</h1><p style={{fontSize:27,lineHeight:1.7,color:c.muted}}>{s.subtitle||s.narration}</p></div><div style={{height:425,flex:1}}><Artwork s={s} p={p}/></div></div>{layout.detail.rows.map((r,i)=>rows[i]?<div key={i} style={{...pos(r),borderTop:'1px solid #dfdfd2',background:'#fdfcfa',padding:'22px 25px',display:'flex',alignItems:'center',fontSize:27,gap:22}}><b style={{color:c.accent}}>{String(i+1).padStart(2,'0')}</b>{rows[i]}</div>:null)}</>}
  if(t.part==='papers')return <><div style={pos({x:0,y:0,w:1920,h:61})}><Nav p={p}/></div><h1 style={{...pos({x:408,y:140,w:1104,h:70}),fontSize:44,margin:0}}>{source(p,5).title}</h1>{layout.papers.cards.map((r,i)=><div key={i} style={pos(r)}><Paper p={p} index={i}/></div>)}</>;
  const s=source(p,7),facts=unique([...(s.items||[]),s.narration,s.subtitle,...(s.details||[])]).filter(v=>v!==s.title);const blocks:Record<number,string>={0:s.title};facts.slice(0,5).forEach((v,i)=>{const head=[1,4,8,12,16][i],body=[2,5,9,13,17][i];blocks[head]=String(i+1).padStart(2,'0');blocks[body]=v;});
  return <><div style={pos({x:0,y:0,w:1920,h:61})}><Nav p={p}/></div><div style={{...pos({x:70,y:145,w:400,h:650}),borderRight:'1px solid #dedecf',fontSize:25,color:c.muted,lineHeight:2}}>内容回顾<br/>{p.scenes.slice(0,5).map((s:any,i:number)=><div key={i} style={{fontSize:20,lineHeight:1.9,marginTop:20}}>{String(i+1).padStart(2,'0')}　{s.title}</div>)}</div>{layout.wbr.blocks.map((b,i)=><div key={i} style={{...pos(b),fontSize:b.tag==='h1'?Math.min(23,Math.floor(b.w/Math.max(1,[...s.title].length))):b.tag==='h2'?18:20,lineHeight:1.45,fontWeight:b.tag==='h1'||b.tag==='h2'?700:400,overflow:'hidden',borderBottom:b.tag==='h2'?'1px solid #dfdfcf':undefined}}>{blocks[i]||''}</div>)}<div style={{...pos({x:1320,y:180,w:450,h:650}),fontSize:27,color:c.accent}}><Artwork s={s} p={p}/><div style={{fontSize:20}}>把过程连起来，看见完整原理</div></div></>;
 };
 return <AbsoluteFill style={{background:'#faf7f2',fontFamily:font,color:c.ink,overflow:'hidden'}}>{render()}</AbsoluteFill>;
}
