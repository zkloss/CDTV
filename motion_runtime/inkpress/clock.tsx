import React,{createContext,useContext} from 'react';
import {useCurrentFrame} from 'remotion';
type Clock={native:number;duration:number;slot:string};
const Context=createContext<Clock|null>(null);
export const TemplateClock=Context.Provider;
export const useTemplateFrame=()=>{
 const f=useCurrentFrame(),clock=useContext(Context);
 if(!clock)return f;
 if(clock.slot==='outro')return Math.min(f,clock.native-14); // keep the completed sign-off readable
 if(clock.slot==='morning'&&clock.duration>clock.native){
  const hold=clock.native-7,extra=clock.duration-clock.native;
  return f<hold?f:f<hold+extra?hold:f-extra;
 }
 return Math.min(f,clock.native-1);
};
