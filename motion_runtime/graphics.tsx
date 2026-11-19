import React from 'react';
import {interpolate,useCurrentFrame} from 'remotion';
const font='"Microsoft YaHei","Segoe UI",sans-serif';
export function illustrationFor(scene:any,theme:string){if(scene.src)return '';if(scene.illustration==='flow')return scene.items?.length?'flow':'';if(scene.illustration)return theme==='botanical'?scene.illustration:scene.items?.length?'flow':'';if(theme!=='botanical')return '';const t=scene.title+' '+scene.subtitle;return /循环|卡尔文|固定/.test(t)?'cycle':/结构|类囊体|基质/.test(t)?'chloroplast':/反应|转换|ATP/.test(t)?'energy':'leaf'}
export function Graphic({kind,colors:c,items=[]}:{kind:string;colors:Record<string,string>;items?:string[]}){
 const frame=useCurrentFrame();const opacity=interpolate(frame,[0,18],[.35,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'});
 const label={fontFamily:font,fontSize:26,fill:c.ink,fontWeight:600};const sub={...label,fontSize:21,fill:c.muted,fontWeight:400};
 const line={stroke:c.accent,strokeWidth:5,fill:'none',strokeLinecap:'round' as const};
 return <svg viewBox="0 0 720 600" style={{width:'100%',maxHeight:'100%',opacity,overflow:'visible'}}>
 <defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8Z" fill={c.accent}/></marker><linearGradient id="leaf"><stop stopColor="#a6cc6a"/><stop offset="1" stopColor="#387950"/></linearGradient></defs>
 {kind==='leaf'&&<>
 <circle cx="555" cy="92" r="44" fill="#efb94d"/>{Array.from({length:8},(_,i)=><line key={i} x1={555+Math.cos(i*Math.PI/4)*62} y1={92+Math.sin(i*Math.PI/4)*62} x2={555+Math.cos(i*Math.PI/4)*80} y2={92+Math.sin(i*Math.PI/4)*80} stroke="#ddb04e" strokeWidth="5"/>)}<text x="555" y="216" textAnchor="middle" {...label}>阳光</text>
 <path d="M195 455 C65 218 310 105 500 220 C490 397 357 468 195 455Z" fill="url(#leaf)" stroke="#36734b" strokeWidth="4"/><path d="M130 530 Q210 420 457 248" stroke="#d5e8b0" strokeWidth="9" fill="none"/>{[0,1,2,3].map(i=><path key={i} d={`M${215+i*53} ${420-i*38} Q${152+i*65} ${340-i*40} ${180+i*70} ${244-i*16}`} stroke="#c1dfa0" strokeWidth="4" fill="none"/>)}
 <path d="M110 170 Q160 180 220 238" {...line} markerEnd="url(#arrow)"/><text x="18" y="120" {...label}>二氧化碳</text><path d="M80 480 Q95 455 155 430" {...line} markerEnd="url(#arrow)"/><text x="24" y="537" {...label}>水</text><path d="M475 355 Q555 365 610 330" {...line} markerEnd="url(#arrow)"/><text x="525" y="393" {...label}>氧气</text><rect x="400" y="470" width="237" height="62" rx="17" fill="#ffffff90" stroke={c.accent}/><text x="518" y="510" textAnchor="middle" {...label}>形成有机物</text><circle cx={460-((frame*1.6)%110)} cy={150+((frame*1.6)%110)} r="7" fill="#e3ad3f"/>
 </>}
 {kind==='chloroplast'&&<>
 <ellipse cx="350" cy="303" rx="288" ry="186" fill="#c9e49e" stroke="#448252" strokeWidth="7"/><ellipse cx="350" cy="303" rx="269" ry="168" fill="none" stroke="#75aa63" strokeWidth="3"/>
 {[0,1,2].map(i=><g key={i}>{[0,1,2,3].map(j=><g key={j}><rect x={157+i*137} y={237+j*21} width="96" height="18" rx="9" fill="#3e8750" stroke="#28643c" strokeWidth="2"/><ellipse cx={205+i*137} cy={237+j*21} rx="48" ry="7" fill="#68a75b"/></g>)}{i<2&&<path d={`M${253+i*137} 299 h41`} stroke="#428052" strokeWidth="7"/>}</g>)}
 <path d="M212 210 L185 65 H75" {...line}/><text x="22" y="48" {...label}>类囊体膜</text><text x="22" y="88" {...sub}>光反应在此进行</text><path d="M515 365 L574 479 H660" {...line}/><text x="484" y="525" {...label}>基质</text><text x="425" y="564" {...sub}>卡尔文循环在此进行</text><text x="350" y="54" textAnchor="middle" {...label}>叶绿体</text>
 </>}
 {kind==='energy'&&<>
 <circle cx="155" cy="166" r="68" fill="#efbf54"/><text x="155" y="175" textAnchor="middle" {...label}>光能</text><path d="M250 166 H455" {...line} markerEnd="url(#arrow)"/><rect x="489" y="96" width="190" height="140" rx="30" fill="#b9d99a"/><text x="584" y="177" textAnchor="middle" {...label}>化学能</text>
 {['吸收光能','水参与反应','形成 ATP 与 NADPH'].map((t,i)=><g key={i}><rect x="82" y={300+i*83} width="570" height="65" rx="16" fill="#ffffffa0" stroke={c.accent}/><circle cx="118" cy={332+i*83} r="16" fill={c.accent}/><text x="118" y={339+i*83} textAnchor="middle" fill="white" fontSize="18">{i+1}</text><text x="155" y={341+i*83} {...label}>{t}</text></g>)}
 </>}
 {kind==='cycle'&&<>
 <circle cx="352" cy="302" r="154" fill="none" stroke="#87b174" strokeWidth="28"/>{[0,1,2].map(i=>{const a=i*Math.PI*2/3-Math.PI/2;return <g key={i}><circle cx={352+Math.cos(a)*154} cy={302+Math.sin(a)*154} r="66" fill="#ecf4e5" stroke={c.accent} strokeWidth="4"/><text x={352+Math.cos(a)*154} y={310+Math.sin(a)*154} textAnchor="middle" {...label}>{['固定','还原','再生'][i]}</text></g>})}<circle cx={352+Math.cos(frame*.025)*154} cy={302+Math.sin(frame*.025)*154} r="10" fill="#e4ac3e"/>
 <text x="352" y="299" textAnchor="middle" {...label}>卡尔文循环</text><text x="352" y="337" textAnchor="middle" {...sub}>发生在叶绿体基质</text><path d="M145 60 L240 130" {...line} markerEnd="url(#arrow)"/><text x="36" y="45" {...label}>二氧化碳</text><path d="M450 455 L540 530" {...line} markerEnd="url(#arrow)"/><text x="515" y="575" {...label}>形成有机物</text>
 </>}
 {kind==='flow'&&items.slice(0,4).map((t,i)=><g key={i}><rect x="35" y={35+i*140} width="650" height="104" rx="22" fill={c.card} stroke={c.accent} strokeWidth="3"/><text x="65" y={97+i*140} fontFamily={font} fontSize="24" fill={c.accent}>0{i+1}</text><foreignObject x="125" y={52+i*140} width="530" height="80"><div style={{fontFamily:font,fontSize:27,lineHeight:1.4,color:c.ink}}>{t}</div></foreignObject>{i<Math.min(items.length,4)-1&&<path d={`M360 ${147+i*140} v15`} {...line} markerEnd="url(#arrow)"/>}</g>)}
 </svg>
}
