# Ink Press 原模板运行组件

来自随应用保留的 video-shotcraft/template/src，完整原技能与目录没有删改。本目录为运行时所需原场景、PageCam、主题及其依赖；LICENSE 保留 Apache-2.0，PROVENANCE.json 记录逐文件原件及适配后哈希。

改动：原场景使用 clock.tsx 映射帧时钟，延长旁白时保持运镜速度并停留在落位状态；片尾保持可见最终构图。PaperTitleCard 使用实际段落时长。SceneOpen 的浮动注释增加纸底，适配中文且避免压住背景卡片文字。InkPressFilm.tsx 保留原10场景顺序、缓动和原音效节拍，传入作品文案。InkPressTextures.tsx 按原 layout 坐标生成自己的26份内容图解贴图，替换原演示品牌和截图。

这次实现的是 Ink Press 整片模板执行器。124张镜头卡及150个效果仍完整保留供规划和查看，不代表每张卡都有独立可执行渲染器。其他未实现模板必须报错，不能悄悄换成通用排版。16:9为原生构图，其他画幅保留完整横幅并留边，不声称逐模板竖屏重新设计。
