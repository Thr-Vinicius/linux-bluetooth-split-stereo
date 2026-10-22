"""Stable trial policy and fresh, window-scoped PipeWire identities.

No I/O at import. Historical IDs are audit data, never device selectors.
"""
import copy
import re

from trial_support import RollbackError


MAC = re.compile(r'(?:[0-9A-F]{2}:){5}[0-9A-F]{2}')
BT_KEYS = ('device.api', 'media.class', 'api.bluez5.address',
           'api.bluez5.profile', 'api.bluez5.codec')


def canonical_mac(value):
    value = str(value).upper()
    if not MAC.fullmatch(value):
        raise RollbackError('Missing or invalid Bluetooth MAC')
    return value


def stamp(sink, node_id, props):
    serial = sink.get('properties', {}).get('object.serial')
    if serial is None or str(props.get('object.serial')) != str(serial):
        raise RollbackError('Pulse and PipeWire resource identities disagree')
    return dict(index=sink['index'], serial=str(serial), node_id=node_id,
                name=sink['name'])


def unique_node(graph, name):
    ids = graph.named(name)
    if len(ids) != 1:
        raise RollbackError('Missing or ambiguous node: ' + name)
    return ids[0], graph.nodes[ids[0]]


def identify(cfg, raw_sinks, graph, modules, expected=None):
    """Resolve current endpoints; compare stable properties, not past IDs.

    Name-only endpoints exist solely in private dummy fixtures. The production
    preparation/executor additionally require both MACs via require_bluetooth().
    """
    names = [s['name'] for s in raw_sinks]
    if len(set(names)) != len(names):
        raise RollbackError('Duplicate Pulse sink names')
    sinks = {s['name']: s for s in raw_sinks}
    stable, current, resolved = {}, {}, copy.deepcopy(cfg)
    for side in ('LEFT', 'RIGHT'):
        mac = cfg.get(side + '_MAC')
        if mac:
            mac = canonical_mac(mac)
            matches = [s for s in raw_sinks if str(s.get('properties', {}).get('api.bluez5.address', '')).upper() == mac]
            nodes = [(n, p) for n, p in graph.nodes.items()
                     if str(p.get('api.bluez5.address', '')).upper() == mac and p.get('media.class') == 'Audio/Sink']
            if len(matches) != 1 or len(nodes) != 1:
                raise RollbackError('Missing or ambiguous Bluetooth endpoint: ' + side)
            sink, (node, props) = matches[0], nodes[0]
            identity = {k: sink['properties'].get(k) for k in BT_KEYS}
            identity['api.bluez5.address'] = mac
            if identity != dict(zip(BT_KEYS, ('bluez5', 'Audio/Sink', mac, 'a2dp-sink', 'aac'))):
                raise RollbackError('Unexpected Bluetooth properties: ' + side)
            identity['factory.name']=sink['properties'].get('factory.name')
            if any(str(props.get(k, '')).upper() != str(v).upper() for k, v in identity.items()):
                raise RollbackError('Pulse/PipeWire Bluetooth properties disagree: ' + side)
            if props.get('node.name') != sink['name'] or not re.fullmatch('bluez_output[.]' + mac.replace(':', '_') + '[.].+', sink['name'], re.IGNORECASE):
                raise RollbackError('Bluetooth name/address mismatch: ' + side)
            resolved[side + '_DEVICE'] = sink['name']
        else:
            sink = sinks[cfg[side + '_DEVICE']]
            node, props = unique_node(graph, sink['name'])
            identity = dict(fixture_name=sink['name'])
        if any(p.get(k) for p in (sink['properties'],props) for k in ('split.owner','split.session')):
            raise RollbackError('Foreign project ownership on physical endpoint')
        stable[side] = identity
        current[side] = stamp(sink, node, props)
    if current['LEFT']['node_id'] == current['RIGHT']['node_id']:
        raise RollbackError('Both sides resolve to the same device')
    virtual = cfg['VIRTUAL_SINK']
    if len(modules) != 1:
        raise RollbackError('Original null module missing or ambiguous')
    module_id, argument = modules[0]
    sink = sinks[virtual]
    node, props = unique_node(graph, virtual)
    if (str(sink.get('owner_module')) != str(module_id) or
            str(props.get('pulse.module.id')) != str(module_id) or
            props.get('factory.name') != 'support.null-audio-sink' or
            props.get('media.class') != 'Audio/Sink' or
            any(p.get(k) for p in (props,sink['properties']) for k in ('split.owner','split.session')) or
            sink.get('channel_map') != 'front-left,front-right'):
        raise RollbackError('Original sink ownership/properties do not match its null module')
    stable['legacy'] = dict(module='module-null-sink', argument=argument,
                            factory='support.null-audio-sink', channel_map=sink['channel_map'])
    current['legacy'] = dict(stamp(sink, node, props), module_id=str(module_id))
    effects = cfg.get('EFFECTS_SINK', 'easyeffects_sink')
    node, props = unique_node(graph, effects)
    if props.get('split.owner') or props.get('split.session'):
        raise RollbackError('Foreign project ownership on effects sink')
    current['effects'] = stamp(sinks[effects], node, props)
    stable['effects'] = dict(name=effects, application_id=props.get('application.id'),
                             factory=props.get('factory.name'), media_class=props.get('media.class'))
    output_name = cfg.get('EFFECTS_OUTPUT_NAME', 'ee_soe_output_level')
    output, props = unique_node(graph, output_name)
    current['effects_output'] = dict(node_id=output, serial=str(props['object.serial']), name=output_name)
    # Pin relevant physical and EE ports for this window too.
    ids = {current[s]['node_id'] for s in ('LEFT', 'RIGHT', 'effects', 'effects_output')}
    current['ports'] = sorted((i, str(p['object.serial']), str(p.get('node.id')), p.get('port.name'), p.get('port.direction'), p.get('audio.channel')) for i, p in graph.ports.items()
                              if int(p.get('node.id', -1)) in ids)
    if expected is not None and stable != expected:
        raise RollbackError('Stable device/module/effects policy changed')
    return dict(stable=stable, current=current, cfg=resolved)


def require_bluetooth(cfg):
    macs = [canonical_mac(cfg.get(s + '_MAC', '')) for s in ('LEFT', 'RIGHT')]
    if macs[0] == macs[1]:
        raise RollbackError('Two different Bluetooth MACs are required')


def audit_difference(historical, current):
    """Record changed current IDs/levels/routes without using them as a gate."""
    fields = ('sinks', 'edges', 'default')
    return {k: dict(previous=historical.get(k), current=current.get(k))
            for k in fields if historical.get(k) != current.get(k)}


def check_window(cfg, raw_sinks, graph, identity):
    """After final capture, even a valid same-MAC recreation is a race, not refresh."""
    names = [s['name'] for s in raw_sinks]
    if len(set(names)) != len(names):
        raise RollbackError('Ambiguous sinks during intervention')
    sinks = {s['name']: s for s in raw_sinks}
    pinned = identity['current']
    for side in ('LEFT', 'RIGHT', 'effects'):
        saved = pinned[side]
        node, props = unique_node(graph, saved['name'])
        if stamp(sinks[saved['name']], node, props) != saved:
            raise RollbackError('Resource changed after final validation: ' + side)
        if side=='effects':
            stable=identity['stable']['effects']
            actual=dict(name=saved['name'],application_id=props.get('application.id'),factory=props.get('factory.name'),media_class=props.get('media.class'))
            if actual!=stable or props.get('split.owner') or props.get('split.session'):
                raise RollbackError('Effects ownership/properties changed')
        if side in ('LEFT', 'RIGHT'):
            if any(p.get(k) for p in (props,sinks[saved['name']]['properties']) for k in ('split.owner','split.session')):
                raise RollbackError('Physical endpoint acquired foreign ownership')
            if cfg.get(side+'_MAC'):
                mac=canonical_mac(cfg[side+'_MAC'])
                if (sum(str(s.get('properties',{}).get('api.bluez5.address','')).upper()==mac for s in raw_sinks)!=1 or
                    sum(str(p.get('api.bluez5.address','')).upper()==mac and p.get('media.class')=='Audio/Sink' for p in graph.nodes.values())!=1):
                    raise RollbackError('Ambiguous Bluetooth identity inside window')
                expected = identity['stable'][side]
                if any(str(props.get(k, '')).upper() != str(v).upper() or
                       str(sinks[saved['name']]['properties'].get(k, '')).upper() != str(v).upper()
                       for k,v in expected.items()):
                    raise RollbackError('Bluetooth properties changed during intervention')
    saved=pinned['effects_output']
    node,props=unique_node(graph,saved['name'])
    if dict(node_id=node,serial=str(props['object.serial']),name=saved['name'])!=saved:
        raise RollbackError('EasyEffects output identity changed')
    ids={pinned[s]['node_id'] for s in ('LEFT','RIGHT','effects','effects_output')}
    ports=sorted((i,str(p['object.serial']),str(p.get('node.id')),p.get('port.name'),p.get('port.direction'),p.get('audio.channel')) for i,p in graph.ports.items() if int(p.get('node.id',-1)) in ids)
    if ports!=pinned['ports']:
        raise RollbackError('Endpoint port identities changed')
    return sinks


def policy_from_history(cfg, snapshot):
    """Extract only stable constraints from an older capture, never its IDs."""
    if 'identity' in snapshot:
        return snapshot['identity']['stable']
    stable={}
    values=list(snapshot['sinks'].values())
    for side in ('LEFT','RIGHT'):
        mac=canonical_mac(cfg[side+'_MAC'])
        matches=[s for s in values if str(s['properties'].get('api.bluez5.address','')).upper()==mac]
        if len(matches)!=1:raise RollbackError('Historical stable endpoint policy is ambiguous')
        stable[side]={k:matches[0]['properties'].get(k) for k in BT_KEYS}
        stable[side]['api.bluez5.address']=mac
        stable[side]['factory.name']=matches[0]['properties'].get('factory.name')
    virtual=snapshot['sinks'][cfg['VIRTUAL_SINK']]
    stable['legacy']=dict(module='module-null-sink',argument=snapshot['legacy']['argument'],
                          factory=virtual['properties'].get('factory.name'),channel_map=virtual['channel_map'])
    name=cfg.get('EFFECTS_SINK','easyeffects_sink');props=snapshot['sinks'][name]['properties']
    stable['effects']=dict(name=name,application_id=props.get('application.id'),
                           factory=props.get('factory.name'),media_class=props.get('media.class'))
    return stable
