"""Decode compatible-provider replies without treating keepalives as answers."""
import json


def decode(response, operation, api_key=''):
    from local_storage import StorageError
    content_type=response.headers.get('content-type','').split(';')[0].lower()
    raw=response.text
    receipt={'httpStatus':response.status_code,'contentType':content_type,
             'responseBytes':len(response.content)}
    def fail(message, kind='transport', **details):
        exc=StorageError(502, operation+message)
        exc.error_kind=kind
        exc.provider_receipt={**receipt,**details}
        raise exc
    try:
        result=response.json()
    except ValueError:
        result=None
    if isinstance(result,dict):return result
    if content_type=='text/event-stream' or any(line.startswith('data:') for line in raw.splitlines()):
        chunks=[]; events=[]; buffer=[];done=False; finished=False;seen=0
        for line in raw.replace('\r\n','\n').split('\n')+['']:
            if line.startswith('data:'):buffer.append(line[5:].lstrip(' '))
            elif not line and buffer:
                events.append('\n'.join(buffer));buffer=[]
        for data in events:
            if data.strip()=='[DONE]':done=True;continue
            try:event=json.loads(data)
            except ValueError:fail('返回的流式数据损坏；没有取得完整答案，请检查接口服务',eventCount=len(events))
            if not isinstance(event,dict):fail('返回的流式事件格式错误',eventCount=len(events))
            seen+=1
            if event.get('error'):
                message=event['error'].get('message','') if isinstance(event['error'],dict) else str(event['error'])
                message=str(message)
                if api_key:message=message.replace(api_key,'[隐藏]')
                fail('服务返回错误：'+message[:300],eventCount=seen)
            if event.get('type')=='message_stop':finished=True
            if event.get('type')=='content_block_delta' and event.get('delta',{}).get('type')=='text_delta':
                chunks.append(str(event['delta'].get('text') or ''))
            for choice in event.get('choices',[]):
                if choice.get('index',0)!=0:continue
                text=(choice.get('delta') or choice.get('message') or {}).get('content')
                if isinstance(text,str):chunks.append(text)
                if choice.get('finish_reason') in ('stop','end_turn'):finished=True
                elif choice.get('finish_reason') in ('length','max_tokens'):
                    finished=True
                elif choice.get('finish_reason') in ('content_filter',):
                    fail('服务商内容审查拦截（content_filter），尚未取得完整方案',eventCount=seen)
        if not chunks or not ''.join(chunks).strip():
            fail('接口只返回保活消息或空流，没有返回答案（HTTP '+str(response.status_code)+'）；请检查该接口及模型是否支持图片和完整回复，反复点击不会修复接口',eventCount=seen,keepaliveOnly=seen==0)
        if not (done or finished):
            if chunks and len(''.join(chunks).strip()) >= 50:
                finished = True
            else:
                fail('的流式回复提前断开，没有完整结束标记；未采用不完整方案',eventCount=seen,incomplete=True)
        return {'choices':[{'message':{'content':''.join(chunks)}}], '_providerReceipt':{**receipt,'eventCount':seen,'streamDecoded':True}}
    if result is not None:fail('返回的 JSON 不是对象，未取得有效回复','schema')
    if content_type=='text/html' or raw.lstrip().lower().startswith(('<!doctype html','<html')):
        fail('接口返回网页而非模型答案（HTTP '+str(response.status_code)+'）；请核对 API 接口路径或网关拦截')
    fail('返回非 JSON 内容（HTTP '+str(response.status_code)+'），没有取得模型答案；请核对 API 接口及返回格式')
