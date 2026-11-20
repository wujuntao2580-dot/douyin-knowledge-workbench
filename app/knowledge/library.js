// The generated catalog remains portable; personal changes use the authenticated local helper.
(() => {
  const embedded = JSON.parse(get('catalog').textContent);
  let personal = embedded.personal;
  let view = 'all', activeGroup = '', activeFolder = '', busy = false;
  let openGroups = new Set();
  const rawTags = new Map(videos.map(video => [video.id, [...video.tags]]));
  const rawVideos = new Map(videos.map(video => [video.id, {...video}]));
  const deletionSelection = new Set();
  let detailVideo = null;
  const connection = /^#vlc=(\d{1,5})\.([A-Za-z0-9_-]+)$/.exec(location.hash);
  const modal = get('personal-dialog');
  const originalOpenDetail = openDetail;

  function node(tag, text, className) {
    const result = document.createElement(tag);
    if (text !== undefined) result.textContent = text;
    if (className) result.className = className;
    return result;
  }
  function control(text, fn, className) {
    const result = node('button', text, className);result.type = 'button';
    result.onclick = () => handle(fn);return result;
  }
  function say(text, error = false) {
    const target = modal.open ? get('personal-message') : get('library-status');
    target.textContent = text;target.hidden = !text;target.classList.toggle('error', error);
  }
  async function handle(fn) {
    try {await fn();} catch(error) {say(error.message, true);}
  }
  async function request(payload) {
    if (!connection) throw Error('请从桌面「知识工作台」打开工作台，以保存主题和收藏。');
    const response = await fetch('http://127.0.0.1:' + connection[1] + '/knowledge', {
      method:'POST',headers:{'X-Playback-Key':connection[2]},body:JSON.stringify(payload),signal:AbortSignal.timeout(15000)
    });
    const text = await response.text();
    if (!response.ok) throw Error(text || '整理请求失败，请刷新页面重试。');
    return JSON.parse(text);
  }
  async function change(payload) {
    if (busy) throw Error('正在保存，请稍候。');
    busy = true;
    const buttons=[...get('personal-body').querySelectorAll('button')];
    const disabled=buttons.map(button=>button.disabled);buttons.forEach(button=>button.disabled=true);
    try {
      personal = await request({...payload,revision:personal.revision});
      applyState();render();
      return personal;
    } finally {busy = false;buttons.forEach((button,index)=>button.disabled=disabled[index]);}
  }
  function canonical(key) {
    const seen = new Set();
    while(personal.aliases[key] && !seen.has(key)) {seen.add(key);key = personal.aliases[key];}
    return key;
  }
  function applyState() {
    for (const key of Object.keys(topics)) delete topics[key];
    for (const [id, topic] of Object.entries(personal.topics)) topics[id] = topic.name;
    for (const video of videos) {
      Object.assign(video, rawVideos.get(video.id));
      video.tags = personal.videos[video.id]?.topics || rawTags.get(video.id).map(canonical);
      const flags=personal.deletions?.[video.id]||{};
      if(flags.media){video.local='';video.hasCompressedVideo=false;}
      if(flags.transcript){video.transcript='';video.subtitle='';video.subtitleTimes=[];}
      if(flags.summary){video.core='';video.points=null;video.pointDisplay={};}
      if(flags.record)deletionSelection.delete(video.id);
    }
    activeTopic = canonical(activeTopic);
    if(activeTopic && !topics[activeTopic]) activeTopic = '';
    if(activeGroup && !personal.groups[activeGroup]) activeGroup = '';
    if(activeFolder && !personal.folders[activeFolder]) activeFolder = '';
  }
  function folderItems() {
    return (activeFolder ? [personal.folders[activeFolder]] : Object.values(personal.folders)).flatMap(folder=>folder.items);
  }
  function hasFavorite(kind, id) {
    return Object.values(personal.folders).some(folder=>folder.items.some(item=>item[0]===kind && item[1]===id));
  }
  function star(kind, id, text = '收藏') {
    const saved = hasFavorite(kind,id);
    const result = control(saved ? '★ 已收藏' : '☆ ' + text,()=>favoriteDialog(kind,id),'bookmark-button'+(saved?' saved':''));
    result.setAttribute('aria-label',(saved?'调整收藏 ':'收藏 ')+(kind==='topic'?topics[id]:videos.find(video=>video.id===id)?.title));
    return result;
  }
  function open(title) {
    modal.classList.remove('delete-mode');
    get('personal-title').textContent = title;get('personal-body').replaceChildren();
    get('personal-message').hidden = true;
    if(!modal.open) modal.showModal();
    return get('personal-body');
  }
  function field(text, input) {
    const row = node('label',undefined,'personal-field');row.append(node('span',text),input);return row;
  }
  function input(value = '', placeholder = '') {
    const item = node('input');item.value = value;item.maxLength = 40;item.placeholder = placeholder;return item;
  }
  function select(items, value, empty) {
    const item = node('select');
    if(empty) item.add(new Option(empty,''));
    for(const [id,name] of items) item.add(new Option(name,id));
    if(value !== undefined) item.value = value;
    return item;
  }
  function groups() {return Object.entries(personal.groups).filter(([id])=>id!=='pending').map(([id,group])=>[id,group.name]);}

  function deleteDialog(ids) {
    const body=open('删除视频（'+ids.length+' 条）');modal.classList.add('delete-mode');
    const form=node('form',undefined,'delete-form');const heading=node('div',undefined,'delete-heading');
    heading.append(node('span','将删除以下内容'),node('span','默认全选'));form.append(heading);
    const options=[['record','工作台记录','该视频的目录项、主题关联和收藏记录'],
      ['media','视频文件','原视频、压缩版视频（.mp4）'],
      ['transcript','口播稿与字幕','逐字稿（.md）、字幕（.srt）、转写文件（.json）'],
      ['summary','摘要文件','摘要 JSON 文件，包含知识要点和对应时间点']];
    const checks=[];
    for(const [key,title,description] of options){
      const label=node('label',undefined,'delete-option');const check=node('input');check.type='checkbox';check.checked=true;check.dataset.deleteKind=key;
      const copy=node('div');copy.append(node('strong',title),node('p',description));label.append(check,copy);form.append(label);checks.push([key,check]);
    }
    const footer=node('div',undefined,'delete-footer');const count=node('span','已选 4 项');
    const buttons=node('div');const cancel=control('取消',()=>modal.close());const confirm=node('button','确认删除','danger');confirm.type='submit';buttons.append(cancel,confirm);footer.append(count,buttons);form.append(footer);
    for(const [,check]of checks)check.onchange=()=>{const n=checks.filter(([,control])=>control.checked).length;count.textContent='已选 '+n+' 项';confirm.disabled=!n;};
    form.onsubmit=event=>{event.preventDefault();handle(async()=>{
      const result=await change({action:'video.delete',ids,choices:Object.fromEntries(checks.map(([key,check])=>[key,check.checked]))});
      if(detailVideo&&ids.includes(detailVideo.id)&&dialog.open)dialog.close();
      const failures=result.deletionResult?.failures||[];
      if(failures.length){say('部分文件未能删除，已保留目录以便重试：'+failures.join('；'),true);return;}
      ids.forEach(id=>deletionSelection.delete(id));modal.close();render();
      say('已处理 '+ids.length+' 条视频；'+result.deletionResult.filesRemoved+' 个本地文件已移入系统回收站。');
    });};body.append(form);
  }

  function favoriteDialog(kind,id) {
    const body = open('收藏到收藏夹');
    body.append(node('p',kind==='topic' ? '收藏小主题后，可随时查看这个主题下的全部视频，后续新归入的视频也会显示。' : videos.find(video=>video.id===id)?.title,'personal-help'));
    const form = node('form',undefined,'personal-form');const checks = [];
    for(const [key,folder] of Object.entries(personal.folders)) {
      const row = node('label',undefined,'folder-check');const check = node('input');check.type='checkbox';
      check.checked=folder.items.some(item=>item[0]===kind&&item[1]===id);checks.push([key,check]);
      row.append(check,node('span',folder.name));form.append(row);
    }
    const save = node('button','保存收藏','primary');save.type='submit';
    form.append(save);form.onsubmit=event=>{event.preventDefault();handle(async()=>{
      await change({action:'favorite.set',kind,id,folders:checks.filter(([,check])=>check.checked).map(([key])=>key)});
      modal.close();say('收藏已保存。');
    });};body.append(form);
    const create = node('div',undefined,'personal-row');const name = input('','新收藏夹名称');
    create.append(name,control('新建收藏夹',async()=>{await change({action:'folder.create',name:name.value});favoriteDialog(kind,id);}));body.append(node('p','也可以创建自己的收藏夹。','personal-help'),create);
  }

  function folderManager() {
    const body=open('管理收藏夹');
    body.append(node('p','收藏夹可同时保存视频和小主题。删除收藏夹只移除其中的收藏记录。','personal-help'));
    for(const [id,folder] of Object.entries(personal.folders)) {
      const row=node('div',undefined,'personal-row manager-item');const name=input(folder.name);
      row.append(name,control('改名',async()=>{await change({action:'folder.rename',id,name:name.value});folderManager();}));
      if(id!=='default') row.append(control('删除',async()=>{
        if(!confirm('删除「'+folder.name+'」及其中的收藏记录？视频和主题会保留。'))return;
        await change({action:'folder.delete',id});folderManager();
      }));body.append(row);
    }
    const name=input('','新收藏夹名称');const row=node('div',undefined,'personal-row');
    row.append(name,control('新建收藏夹',async()=>{await change({action:'folder.create',name:name.value});folderManager();},'primary'));body.append(row);
  }

  function assignmentDialog(video) {
    const setting=personal.videos[video.id];const body=open('确认视频的主题归属');
    body.append(node('p',video.title,'personal-help'));
    const suggested=(setting?.suggested||[]).map(id=>{
      const topic=personal.topics[id];return (personal.groups[topic?.group]?.name||'待归类')+' › '+(topic?.name||id);
    });body.append(node('p','系统推荐：'+(suggested.join('、')||'暂无推荐，请选择小主题。'),'personal-help'));
    const chosen=new Set(setting?.topics?.length?setting.topics:setting?.suggested||[]);
    const form=node('form',undefined,'personal-form');const group=select(groups(),'','所有大主题');
    const search=input('','筛选小主题');const list=node('div',undefined,'assignment-topics');
    function draw(){
      list.replaceChildren();
      for(const [id,topic] of Object.entries(personal.topics)) {
        if(topic.state!=='confirmed'||group.value&&topic.group!==group.value||!topic.name.includes(search.value.trim()))continue;
        const row=node('label',undefined,'assignment-check');const check=node('input');check.type='checkbox';check.checked=chosen.has(id);
        check.onchange=()=>{if(check.checked)chosen.add(id);else chosen.delete(id);};
        const text=node('span',topic.name);text.append(node('small',personal.groups[topic.group].name));row.append(check,text);list.append(row);
      }
    }
    group.onchange=draw;search.oninput=draw;draw();
    form.append(field('按大主题筛选',group),search,list);
    const save=node('button','确认归属','primary');save.type='submit';form.append(save);
    form.onsubmit=event=>{event.preventDefault();handle(async()=>{
      await change({action:'video.assign',id:video.id,topics:[...chosen].filter(id=>personal.topics[id]?.state==='confirmed')});
      modal.close();say('主题归属已确认，后续重新整理会保留这次选择。');
      if(dialog.open)openDetail(video);
    });};body.append(form);
    if((setting?.suggested||[]).some(id=>personal.topics[id]?.state==='pending'))body.append(node('p','部分新小主题尚未确定归属，可先在「管理主题」中处理，或改选已有小主题。','personal-help'));
    body.append(control('改为自动归属',async()=>{await change({action:'video.auto',id:video.id});modal.close();say('已按推荐主题自动归属；不明确的新主题仍会保留待确认。');}));
  }

  function topicManager(tab='topics', selected='') {
    const body=open('管理知识主题');const tabs=node('div',undefined,'manager-tabs');
    tabs.append(control('小主题',()=>topicManager('topics'),' '+(tab==='topics'?'active':'')),control('大主题',()=>topicManager('groups'),' '+(tab==='groups'?'active':'')));body.append(tabs);
    body.append(node('p','改名不改变视频和收藏的关联；合并后，原有视频与收藏会归到目标主题。','personal-help'));
    if(tab==='groups') {
      for(const [id,group] of Object.entries(personal.groups)) {
        if(id==='pending')continue;
        const box=node('section',undefined,'manager-item');const name=input(group.name);
        const rename=node('div',undefined,'personal-row');rename.append(name,control('改名',async()=>{await change({action:'group.rename',id,name:name.value});topicManager('groups');}));
        const target=select(groups().filter(([key])=>key!==id),'','选择要合并到的大主题');const merge=node('div',undefined,'personal-row');
        merge.append(target,control('合并',async()=>{if(!target.value)throw Error('请先选择合并目标');if(!confirm('将「'+group.name+'」合并到选中的大主题？'))return;await change({action:'group.merge',id,target:target.value});topicManager('groups');}));box.append(rename,merge);body.append(box);
      }
      const name=input('','新大主题名称');const row=node('div',undefined,'personal-row');row.append(name,control('新增大主题',async()=>{await change({action:'group.create',name:name.value});topicManager('groups');},'primary'));body.append(row);return;
    }
    const search=input('','搜索要调整的小主题');search.className='search-topic';body.append(search);const list=node('div');body.append(list);
    function draw(){
      list.replaceChildren();
      for(const [id,topic] of Object.entries(personal.topics)) {
        if(search.value&&!topic.name.includes(search.value))continue;
        const box=node('section',undefined,'manager-item');box.dataset.topic=id;
        const title=node('h4',topic.name+(topic.state==='pending'?' · 待确认':''));box.append(title);
        if(topic.reason)box.append(node('p',topic.reason+(topic.similar?'：'+topics[topic.similar]:''),'personal-help'));
        const name=input(topic.name);const rename=node('div',undefined,'personal-row');rename.append(name,control('改名',async()=>{await change({action:'topic.rename',id,name:name.value});topicManager('topics',id);}));
        const group=select(groups(),topic.group==='pending'?topic.suggestedGroup:topic.group,'选择大主题');const move=node('div',undefined,'personal-row');
        move.append(group,control(topic.state==='pending'?'确认归属':'调整归属',async()=>{await change({action:'topic.move',id,group:group.value});topicManager('topics',id);}));
        const candidates=Object.entries(personal.topics).filter(([key,t])=>key!==id&&t.state==='confirmed').map(([key,t])=>[key,personal.groups[t.group].name+' › '+t.name]);
        const target=select(candidates,topic.similar||'','选择要合并到的小主题');const merge=node('div',undefined,'personal-row');
        merge.append(target,control('合并',async()=>{if(!target.value)throw Error('请先选择合并目标');if(!confirm('将「'+topic.name+'」合并到选中的小主题？'))return;await change({action:'topic.merge',id,target:target.value});topicManager('topics');}));
        box.append(rename,move,merge);list.append(box);
      }
      if(selected)list.querySelector('[data-topic="'+CSS.escape(selected)+'"]')?.scrollIntoView({block:'nearest'});
    }
    search.oninput=draw;draw();
  }

  const aside=document.querySelector('aside');
  const nav=node('div',undefined,'personal-nav');aside.prepend(nav);
  const heading=node('div',undefined,'topic-heading');const oldHeading=aside.querySelector('h2');oldHeading.textContent='知识主题';oldHeading.replaceWith(heading);heading.append(oldHeading,control('管理',()=>topicManager()));
  const main=document.querySelector('.layout>main');const statusNode=node('p','','');statusNode.id='library-status';statusNode.setAttribute('role','status');statusNode.hidden=true;main.prepend(statusNode);
  const toolbar=node('div',undefined,'collection-toolbar');toolbar.id='collection-toolbar';toolbar.hidden=true;main.insertBefore(toolbar,main.querySelector('.filters'));
  const favoriteTopics=node('section');favoriteTopics.id='favorite-topics';favoriteTopics.setAttribute('aria-label','收藏的小主题');main.insertBefore(favoriteTopics,get('cards'));
  const reviewTopics=node('section');reviewTopics.id='review-topics';main.insertBefore(reviewTopics,get('cards'));
  const deleteBar=node('div',undefined,'delete-bar');deleteBar.id='video-selection';main.insertBefore(deleteBar,get('cards'));
  const titleBox=node('div',undefined,'results-title');const activeHeading=get('active-topic');activeHeading.replaceWith(titleBox);titleBox.append(activeHeading);

  selectTopic = function(id) {
    activeTopic=id;activeGroup=personal.topics[id]?.group||'';view='all';currentPage=1;
    if(activeGroup)openGroups.add(activeGroup);if(dialog.open)dialog.close();render();
    get('active-topic').scrollIntoView({block:'nearest'});
  };
  openDetail = function(video) {
    detailVideo=video;
    originalOpenDetail(video);
    const actions=get('actions');actions.append(star('video',video.id),control('调整主题归属',()=>assignmentDialog(video)),control('删除视频',()=>deleteDialog([video.id]),'delete-link'));
  };

  render = function() {
    const creator=get('creator').value;
    const available=videos.filter(video=>!personal.deletions?.[video.id]?.record);
    document.querySelector('.hero p').textContent=new Set(available.map(video=>video.creatorId)).size+' 位主播 · '+available.length+' 条视频';
    const terms=get('query').value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const base=available.filter(video=>{
      if(creator&&video.creatorId!==creator)return false;
      const names=video.tags.flatMap(id=>[topics[id],personal.groups[personal.topics[id]?.group]?.name]);
      const source=[video.title,video.core,video.detail,...(video.points||[]).flat(),...names,video.transcript,video.id].join(' ').toLowerCase();
      return terms.every(term=>source.includes(term));
    });
    nav.replaceChildren();
    const pending=available.filter(video=>personal.videos[video.id]?.pending).length;
    const favoriteCount=new Set(Object.values(personal.folders).flatMap(folder=>folder.items.map(item=>item.join(':')))).size;
    for(const [id,name,count] of [['all','全部内容',available.length],['favorites','我的收藏',favoriteCount],['review','待确认归属',pending]]) {
      const button=control('',()=>{view=id;activeTopic='';activeGroup='';currentPage=1;render();},id===view?'active':'');button.append(node('span',name),node('span',String(count),'count'));nav.append(button);
    }
    const tree=get('topics');tree.replaceChildren();
    for(const [groupId,group] of Object.entries(personal.groups)) {
      const members=Object.entries(personal.topics).filter(([,topic])=>topic.group===groupId);
      const relevant=members.filter(([id])=>base.some(video=>video.tags.includes(id))||id===activeTopic);
      if(!relevant.length&&groupId==='pending')continue;
      const detail=node('details',undefined,'theme-group');detail.open=openGroups.has(groupId)||activeGroup===groupId;
      detail.ontoggle=()=>{if(detail.open)openGroups.add(groupId);else openGroups.delete(groupId);};
      const summary=node('summary');summary.classList.toggle('active',activeGroup===groupId&&!activeTopic);
      const count=base.filter(video=>video.tags.some(id=>personal.topics[id]?.group===groupId)).length;
      const groupButton=control('',()=>{activeGroup=groupId;activeTopic='';view='all';currentPage=1;openGroups.add(groupId);render();});groupButton.append(node('span',group.name),node('span',String(count),'count'));summary.append(groupButton);detail.append(summary);
      const children=node('div',undefined,'theme-topics');
      for(const [id,topic] of relevant) {
        const row=node('div',undefined,'topic-item');const button=control('',()=>selectTopic(id));button.setAttribute('aria-pressed',String(id===activeTopic));
        button.append(node('span',topic.name),node('span',String(base.filter(video=>video.tags.includes(id)).length),'count'));
        const bookmark=control(hasFavorite('topic',id)?'★':'☆',()=>favoriteDialog('topic',id),'star-button'+(hasFavorite('topic',id)?' saved':''));bookmark.setAttribute('aria-label','收藏小主题 '+topic.name);row.append(button,bookmark);children.append(row);
      }
      detail.append(children);tree.append(detail);
    }
    toolbar.replaceChildren();toolbar.hidden=view!=='favorites';favoriteTopics.replaceChildren();reviewTopics.replaceChildren();
    let shown=base;
    if(view==='favorites') {
      toolbar.append(node('h2','我的收藏'));const folder=select(Object.entries(personal.folders).map(([id,f])=>[id,f.name]),activeFolder,'所有收藏夹');folder.setAttribute('aria-label','收藏夹筛选');folder.onchange=()=>{activeFolder=folder.value;currentPage=1;render();};toolbar.append(folder,control('管理收藏夹',folderManager));
      const items=folderItems();const topicIds=new Set(items.filter(([kind])=>kind==='topic').map(([,id])=>id));
      for(const id of topicIds) {
        const topic=personal.topics[id];if(!topic)continue;
        const relevant=base.filter(video=>video.tags.includes(id));if((creator||terms.length)&&!relevant.length)continue;
        const tile=node('div',undefined,'favorite-topic');const button=control(topic.name,()=>selectTopic(id));button.append(node('small',personal.groups[topic.group].name+' · '+relevant.length+' 条视频'));
        tile.append(button,control('★',()=>favoriteDialog('topic',id)));favoriteTopics.append(tile);
      }
      const ids=new Set(items.filter(([kind])=>kind==='video').map(([,id])=>id));shown=shown.filter(video=>ids.has(video.id));
    } else if(view==='review') {
      shown=shown.filter(video=>personal.videos[video.id]?.pending);
      for(const [id,topic] of Object.entries(personal.topics)) {
        if(topic.state!=='pending')continue;
        const box=node('div',undefined,'review-topic');box.append(node('strong','新小主题：'+topic.name),node('p',topic.reason+(topic.similar?'，可能与「'+topics[topic.similar]+'」重复。':'')),control('确认或合并',()=>topicManager('topics',id)));reviewTopics.append(box);
      }
    } else shown=shown.filter(video=>(!activeTopic||video.tags.includes(activeTopic))&&(!activeGroup||video.tags.some(id=>personal.topics[id]?.group===activeGroup)));
    const sign=get('order').value==='oldest'?1:-1;
    shown=[...shown].sort((a,b)=>sign*a.date.localeCompare(b.date)||a.id.localeCompare(b.id));
    get('active-topic').textContent=view==='favorites'?'收藏的视频':view==='review'?'推荐归属，等你确认':activeTopic?(personal.groups[personal.topics[activeTopic]?.group]?.name+' › '+topics[activeTopic]):activeGroup?personal.groups[activeGroup].name:'全部视频';
    for(const button of titleBox.querySelectorAll('button'))button.remove();
    if(activeTopic&&view==='all')titleBox.append(star('topic',activeTopic,'收藏小主题'));
    get('count').textContent=shown.length+' 条';
    deleteBar.replaceChildren();const all=node('label',undefined,'selection-check');const allCheck=node('input');allCheck.type='checkbox';allCheck.checked=Boolean(shown.length&&shown.every(video=>deletionSelection.has(video.id)));allCheck.indeterminate=shown.some(video=>deletionSelection.has(video.id))&&!allCheck.checked;
    allCheck.onchange=()=>{shown.forEach(video=>{if(allCheck.checked)deletionSelection.add(video.id);else deletionSelection.delete(video.id);});render();};all.append(allCheck,node('span','全选当前结果'));
    const selectedCount=node('span',deletionSelection.size?'已选 '+deletionSelection.size+' 条':'','selection-count');const remove=control('删除视频',()=>deleteDialog([...deletionSelection]),'delete-selected');remove.disabled=!deletionSelection.size;deleteBar.append(all,selectedCount,remove);
    const count=Math.max(1,Math.ceil(shown.length/pageSize));currentPage=Math.min(currentPage,count);
    get('previous').disabled=currentPage===1;get('next').disabled=currentPage===count;get('page-count').textContent=currentPage+' / '+count;get('page-count').parentElement.hidden=count===1;
    const cards=get('cards');cards.replaceChildren();
    if(!shown.length)cards.append(node('p',view==='favorites'?'这个收藏夹还没有匹配的视频，可收藏视频或点击上方的小主题。':view==='review'?'当前没有需要确认的视频。':available.length?'当前筛选没有视频。':'知识库为空，点击右上角「下载与入库」添加自己的视频。','muted'));
    for(const video of shown.slice((currentPage-1)*pageSize,currentPage*pageSize)) {
      const card=node('article');card.dataset.id=video.id;
      const meta=node('div',undefined,'card-meta-row');const copy=node('p',video.creator+' · '+video.date,'meta');
      const setting=personal.videos[video.id];if(setting?.pending)copy.append(node('span','待确认归属','review-badge'));
      const picker=node('input',undefined,'video-pick');picker.type='checkbox';picker.checked=deletionSelection.has(video.id);picker.setAttribute('aria-label','选择删除 '+video.title);picker.onchange=()=>{if(picker.checked)deletionSelection.add(video.id);else deletionSelection.delete(video.id);render();};
      const metaCopy=node('div',undefined,'card-meta-copy');metaCopy.append(picker,copy);meta.append(metaCopy,star('video',video.id));card.append(meta);
      const openCard=control('',()=>openDetail(video),'open-card');openCard.append(node('strong',video.title),node('span','查看详情 ›'));card.append(openCard,node('p',video.core||(video.transcript?'摘要待整理 · 有口播稿':'待转写'),video.core?'core':'meta'));
      if(video.points) {
        const list=node('ul',undefined,'points');
        for(const [time,text] of video.points) {
          const item=node('li');const [heading,description]=video.pointDisplay?.[time]||[text,''];item.append(node('strong',heading));if(description)item.append(node('span',description,'point-description'));list.append(item);
        }card.append(list);
      }
      const tags=node('div',undefined,'tags');addTags(tags,video.tags);card.append(tags);
      if(setting?.pending) {
        card.append(node('p','推荐：'+setting.suggested.map(id=>topics[id]).join('、'),'suggested-tags'),control('确认或调整归属',()=>assignmentDialog(video),'review-action'));
      }
      cards.append(card);
    }
  };
  get('personal-close').onclick=()=>modal.close();
  applyState();
  if(connection)request({action:'state'}).then(result=>{personal=result;applyState();render();}).catch(error=>say('无法读取最新收藏：'+error.message,true));
  else say('当前为离线页面快照；从桌面入口打开可保存收藏和主题调整。');
})();
