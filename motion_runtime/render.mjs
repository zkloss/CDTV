import {bundle} from '@remotion/bundler';
import {selectComposition,renderMedia,renderStill,openBrowser,makeCancelSignal,getVideoMetadata} from '@remotion/renderer';
import {readFile,mkdir,cp} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const [spec,output,publicDir,browserExecutable]=process.argv.slice(2);
if(!spec||!output||!publicDir||!browserExecutable)throw new Error('Missing renderer arguments');
const plan=JSON.parse(await readFile(spec,'utf8'));
const root=path.dirname(fileURLToPath(import.meta.url));
const log=(progress,message)=>process.stdout.write(JSON.stringify({progress,message})+'\n');
const {cancelSignal,cancel}=makeCancelSignal();let cancelled=false;
process.stdin.setEncoding('utf8');process.stdin.on('data',()=>{cancelled=true;cancel()});process.stdin.resume();
let browser;
try{
 log(0,'准备整片画面');
 const serveUrl=await bundle({entryPoint:path.join(root,'film.tsx'),publicDir,webpackOverride:config=>({...config,cache:false}),onProgress:p=>log(p*.001,'准备整片画面')});
 let assetCount=0;
 if(plan.templateId==='ink-press'){
  const layout=JSON.parse(await readFile(path.join(root,'inkpress/aifl/live-layout.json'),'utf8'));
  const task=(file,w,h,part,index=0,scale=2)=>({file,w:Math.ceil(w),h:Math.ceil(h),part,index,scale});
  const tasks=[task('projects-full.png',1920,layout.projects.pageH,'projects'),task('projects-empty.png',1920,layout.projects.pageH,'empty'),task('detail-full.png',1920,layout.detail.pageH,'detail'),task('papers-full.png',1920,layout.papers.pageH,'papers'),task('wbr-full.png',1920,layout.wbr.pageH,'wbr'),...layout.projects.cards.map((r,i)=>task(r.file,r.w,r.h,'tile',i)),task('card4-hires.png',layout.projects.cards[3].w,layout.projects.cards[3].h,'tile',3,4),...layout.papers.cards.map((r,i)=>task(`paper${i+1}.png`,r.w,r.h,'paper',i)),...layout.float.map((r,i)=>task(r.file,r.w,r.h,'float',i)),task('nav.png',1920,61,'nav')];
  await mkdir(path.join(publicDir,'textures/live'),{recursive:true});
  browser=await openBrowser('chrome',{browserExecutable,chromeMode:'chrome-for-testing',chromiumOptions:{gl:'angle'}});
  const base=await selectComposition({serveUrl,id:'CdtvInkTexture',inputProps:{plan,texture:tasks[0]},puppeteerInstance:browser});
  for(const t of tasks){
   if(cancelled)throw new Error('Cancelled');
   const inputProps={plan,texture:t};
   await renderStill({serveUrl,composition:{...base,width:t.w,height:t.h,props:inputProps},inputProps,frame:30,imageFormat:'png',scale:t.scale,output:path.join(publicDir,'textures/live',t.file),puppeteerInstance:browser,cancelSignal,timeoutInMilliseconds:120000});
   assetCount++;log(.02+.08*assetCount/tasks.length,`正在适配 Ink Press 素材 ${assetCount}/${tasks.length}`);
  }
  // bundle() snapshots publicDir before these generated textures exist.
  await cp(path.join(publicDir,'textures'),path.join(serveUrl,'public/textures'),{recursive:true});
 }
 const composition=await selectComposition({serveUrl,id:'CdtvWholeFilm',inputProps:plan,browserExecutable,puppeteerInstance:browser,chromiumOptions:{gl:'angle'},chromeMode:'chrome-for-testing'});
 if(cancelled)throw new Error('Cancelled');
 await renderMedia({serveUrl,composition,codec:'h264',outputLocation:output,inputProps:plan,browserExecutable,puppeteerInstance:browser,chromeMode:'chrome-for-testing',concurrency:2,pixelFormat:'yuv420p',crf:19,cancelSignal,chromiumOptions:{gl:'angle'},timeoutInMilliseconds:120000,onProgress:({progress})=>log(.1+progress*.9,plan.templateId==='ink-press'?'正在渲染 Ink Press 原版镜头':'正在渲染整片')});
 const metadata=await getVideoMetadata(output);metadata.rendererKind=plan.templateId==='ink-press'?'ink-press-native-v1':'general-layout-v2';metadata.templateAssetCount=assetCount;metadata.templateComponents=plan.templateComponents||[];process.stdout.write(JSON.stringify({metadata})+'\n');
 log(1,'整片渲染完成');
}catch(err){process.stderr.write(String(err?.stack||err)+'\n');process.exitCode=1;}finally{if(browser)await browser.close({silent:true});process.stdin.pause();process.stdin.destroy();}
