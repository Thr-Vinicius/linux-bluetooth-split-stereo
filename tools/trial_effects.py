"""Read-only EasyEffects activity/route classification, independent of MPRIS."""
from trial_support import RollbackError
from trial_identity import unique_node


APP = 'com.github.wwmm.easyeffects'


class EffectsPending(RollbackError):
    """A possibly transient incomplete path; never approval for an intervention."""
    pass


def candidate(props, cfg):
    if not props.get('split.owner'):return False
    if props.get('split.owner')=='linux-bluetooth-split-stereo' and props.get('split.session')==cfg.get('TRIAL_TOKEN') and cfg.get('TRIAL_TOKEN'):
        return True
    raise RollbackError('Foreign ownership on a playback stream')


def effects_owner(cfg, graph):
    sink, props = unique_node(graph, cfg.get('EFFECTS_SINK', 'easyeffects_sink'))
    output, out = unique_node(graph, cfg.get('EFFECTS_OUTPUT_NAME', 'ee_soe_output_level'))
    # The name-only private stand-in is the same null node. Production requires
    # the real application ID in trial-supervisor, never this stand-in.
    if sink == output and props.get('application.id') is None:
        return sink, output, None
    if (props.get('application.id') != APP or out.get('application.id') != APP or
            props.get('client.id') is None or str(out.get('client.id')) != str(props['client.id']) or
            any(p.get(k) for p in (props, out) for k in ('split.owner', 'split.session'))):
        raise RollbackError('EasyEffects sink/output ownership is not coherent')
    client = graph.objects.get(int(props['client.id']), {})
    cp = client.get('info', {}).get('props', {})
    if (not client.get('type', '').endswith(':Client') or
            cp.get('application.process.binary') != 'easyeffects' or
            cp.get('application.name') != 'easyeffects' or cp.get('object.serial') is None):
        raise RollbackError('Cannot identify the EasyEffects owner client')
    return sink, output, str(props['client.id'])


def classify(cfg, graph, inputs):
    """IDLE is preparable, never proof that playback is ready for intervention.

    A running native node, an active link into EE, or an uncorked Pulse input
    counts as activity. MPRIS, sample amplitudes and sink RUNNING alone do not.
    Existing wrong/crossed/duplicate links fail even while idle.
    """
    sink, output, client = effects_owner(cfg, graph)
    virtual, _ = unique_node(graph, cfg['VIRTUAL_SINK'])
    relevant = []
    active = set()
    graph_streams = {n: p for n, p in graph.nodes.items()
                     if p.get('media.class') == 'Stream/Output/Audio' and not candidate(p,cfg)}
    for item in inputs:
        if candidate(item['properties'],cfg):
            continue
        if item.get('restore_sink') != cfg.get('EFFECTS_SINK', 'easyeffects_sink'):
            raise RollbackError('Playback stream targets an output outside the reviewed EE path')
        serial = item['properties'].get('object.serial')
        matches = [n for n, p in graph_streams.items() if str(p.get('object.serial')) == str(serial)]
        if serial is None or len(matches) != 1:
            raise EffectsPending('Playback stream disappeared or is ambiguous; recapture required')
        if not item['corked']:
            active.add(matches[0])
    arcs = []
    active_arcs = set()
    for link, a, b, state in graph.links:
        pa, pb = graph.ports[a], graph.ports[b]
        source, target = int(pa['node.id']), int(pb['node.id'])
        ch, dest_ch = pa.get('audio.channel'), pb.get('audio.channel')
        if source == output or target == virtual:
            row = (source, ch, target, dest_ch)
            if source != output or target != virtual or ch != dest_ch or ch not in ('FL', 'FR'):
                raise RollbackError('Wrong, crossed or unsettled EasyEffects output route')
            if state=='error':raise RollbackError('EasyEffects output link is in error')
            if state not in ('active','paused'):raise EffectsPending('EasyEffects output link is negotiating')
            relevant.append(row)
        if source in graph_streams:
            if target != sink:
                raise RollbackError('Native playback stream bypasses the reviewed EE path')
            if state == 'active':
                active.add(source)
        if ch == dest_ch and state in ('active', 'paused'):
            arcs.append((source, target, ch))
            if state=='active':active_arcs.add((source,target,ch))
    for n in graph_streams:
        if graph.objects[n]['info'].get('state') == 'running':
            active.add(n)
    expected = {(output, ch, virtual, ch) for ch in ('FL', 'FR')}
    complete = len(relevant) == 2 and set(relevant) == expected
    if relevant and not complete:
        if len(relevant)!=len(set(relevant)):raise RollbackError('Duplicate EasyEffects stereo route')
        raise EffectsPending('Incomplete EasyEffects stereo route')
    if active and not all((output,virtual,ch) in active_arcs for ch in ('FL','FR')):
        raise EffectsPending('Effective playback output links are absent or not active')
    if active and not complete:
        raise EffectsPending('Effective playback has no complete EasyEffects output route')
    # Follow both channel paths from EE monitor to its final meter. A named
    # output link alone cannot prove that the processing pipeline exists.
    if active:
        for channel in ('FL', 'FR'):
            reached, pending = {sink}, [sink]
            while pending:
                n = pending.pop()
                for src, dst, ch in arcs:
                    if src != n or ch != channel or dst == virtual or dst in reached or (src,dst,ch) not in active_arcs:
                        continue
                    p = graph.nodes[dst]
                    if client is not None and (str(p.get('client.id')) != client or p.get('application.id') != APP):
                        raise RollbackError('Foreign owner inside the EasyEffects processing path')
                    reached.add(dst); pending.append(dst)
            if output not in reached:
                raise EffectsPending('Effective playback has an incomplete EasyEffects processing path')
        for n in active - {sink}:
            if not any(src == n and dst == sink for src, dst, _ in active_arcs):
                raise EffectsPending('Effective playback stream has no established link into EasyEffects')
    return dict(state='ACTIVE_VERIFIED' if active else 'IDLE_UNPROVEN',
                playback_ready=bool(active), output_links=len(relevant),
                active_nodes=sorted(active))


def output_stamp(graph, node, props):
    client=props.get('client.id')
    return dict(node_id=node, serial=str(props['object.serial']), name=props['node.name'],
                client_id=str(client), client_serial=str(graph.objects.get(int(client), {}).get('info', {}).get('props', {}).get('object.serial')) if client is not None else None)


def witness(cfg, graph, inputs):
    """Relevant topology/activity, excluding latency counters and MPRIS."""
    interested={n for n,p in graph.nodes.items() if p.get('application.id')==APP or
                p.get('media.class')=='Stream/Output/Audio' or p.get('node.name') in
                (cfg['VIRTUAL_SINK'],cfg.get('EFFECTS_SINK','easyeffects_sink'))}
    links=sorted((i,a,b,state) for i,a,b,state in graph.links
                 if int(graph.ports[a]['node.id']) in interested or int(graph.ports[b]['node.id']) in interested)
    streams=sorted((n,str(p.get('object.serial')),graph.objects[n]['info'].get('state'))
                   for n,p in graph.nodes.items() if p.get('media.class')=='Stream/Output/Audio')
    pulse=sorted((str(i['properties'].get('object.serial')),i['sink'],i['corked']) for i in inputs)
    return links,streams,pulse
