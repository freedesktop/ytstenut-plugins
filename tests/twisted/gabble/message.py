#!/usr/bin/env python
#
# Copyright (C) 2011 Intel Corp.
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA
# 02110-1301 USA

from gabbleservicetest import call_async, EventPattern, assertEquals, ProxyWrapper
from gabbletest import exec_test, make_result_iq, sync_stream
from gabblecaps_helper import presence_and_disco

from twisted.words.protocols.jabber.client import IQ
from twisted.words.xish.domish import Element

import gabbleconstants as cs
import yconstants as ycs
import ns

client = 'http://telepathy.im/fake'
caps = {'ver': '0.1', 'node': client}
features = [
    ns.JINGLE_015,
    ns.JINGLE_015_AUDIO,
    ns.JINGLE_015_VIDEO,
    ns.GOOGLE_P2P,
    ycs.SERVICE_NS + '#the.target.service'
    ]
identity = ['client/pc/en/Lolclient 0.L0L']

def wrap_channel(bus, conn, path):
    return ProxyWrapper(bus.get_object(conn.bus_name, path),
                        ycs.CHANNEL_IFACE, {})

def setup_tests(q, bus, conn, stream, announce=False):
    bare_jid = "test-yst-message@example.com"
    full_jid = bare_jid + "/HotHotResource"

    if announce:
        presence_and_disco(q, conn, stream, full_jid,
                           True, client, caps,
                           features, identity, {},
                           True, None)

        sync_stream(q, stream)

    handle = conn.RequestHandles(cs.HT_CONTACT, [full_jid])[0]

    return handle, bare_jid, full_jid

def setup_outgoing_tests(q, bus, conn, stream, announce=True):
    handle, _, _ = setup_tests(q, bus, conn, stream, announce)

    # okay we got our contact, let's go
    request_props = {
        cs.CHANNEL_TYPE: ycs.CHANNEL_IFACE,
        cs.TARGET_HANDLE_TYPE: cs.HT_CONTACT,
        cs.TARGET_HANDLE: handle,
        ycs.REQUEST_TYPE: ycs.REQUEST_TYPE_GET,
        ycs.REQUEST_ATTRIBUTES: {'hi': 'mom'},
        ycs.TARGET_SERVICE: 'the.target.service',
        ycs.INITIATOR_SERVICE: 'the.initiator.service'
        }

    call_async(q, conn.Requests, 'CreateChannel', request_props)

    e, _ = q.expect_many(EventPattern('dbus-return', method='CreateChannel'),
                         EventPattern('dbus-signal', signal='NewChannels'))
    path, props = e.value

    for k, v in request_props.items():
        assertEquals(v, props[k])

    # finally we have our channel
    chan = wrap_channel(bus, conn, path)

    # let's check we can't call Fail()/Reply()
    call_async(q, chan, 'Fail', ycs.ERROR_TYPE_CANCEL, 'lol', 'whut', 'pear')
    q.expect('dbus-error', method='Fail')

    call_async(q, chan, 'Reply', {'lol':'whut'}, '')
    q.expect('dbus-error', method='Reply')

    # okay enough, let's move on.
    call_async(q, chan, 'Request')

    e, _ = q.expect_many(EventPattern('stream-iq'),
                         EventPattern('dbus-return', method='Request'))

    assertEquals('get', e.iq_type)
    assertEquals('message', e.query_name)
    assertEquals('urn:ytstenut:message', e.query_ns)

    # we shouldn't be able to call this again
    call_async(q, chan, 'Request')
    q.expect('dbus-error', method='Request')

    return path, e.stanza

def outgoing_reply(q, bus, conn, stream):
    path, stanza = setup_outgoing_tests(q, bus, conn, stream)

    # reply with nothing
    reply = make_result_iq(stream, stanza)
    stream.send(reply)

    e = q.expect('dbus-signal', signal='Replied', path=path)
    args, xml = e.args
    assertEquals({}, args)
    assertEquals('<?xml version="1.0" encoding="UTF-8"?>\n' \
                 + '<message xmlns="urn:ytstenut:message"/>\n', xml)

def outgoing_fail(q, bus, conn, stream):
    path, stanza = setup_outgoing_tests(q, bus, conn, stream)

    # construct a nice error reply
    reply = IQ(None, 'error')
    reply['id'] = stanza['id']
    reply['from'] = stanza['to']
    error = reply.addElement('error')
    error['type'] = 'cancel'
    error['code'] = '409'
    error.addElement((ns.STANZA, 'conflict'))
    error.addElement((ycs.MESSAGE_NS, 'yodawg'))
    text = error.addElement((ns.STANZA, 'text'),
                            content='imma let you finish')

    stream.send(reply)

    e = q.expect('dbus-signal', signal='Failed', path=path)
    error_type, stanza_error_name, yst_error_name, text = e.args
    assertEquals(ycs.ERROR_TYPE_CANCEL, error_type)
    assertEquals('conflict', stanza_error_name)
    assertEquals('yodawg', yst_error_name)
    assertEquals('imma let you finish', text)

def bad_requests(q, bus, conn, stream):
    handle, _, _ = setup_tests(q, bus, conn, stream)

    props = {
        cs.CHANNEL_TYPE: ycs.CHANNEL_IFACE,
        cs.TARGET_HANDLE_TYPE: cs.HT_CONTACT,
        }

    def ensure_error(extra={}):
        copy = props.copy()
        copy.update(extra)

        call_async(q, conn.Requests, 'CreateChannel', copy)
        q.expect('dbus-error', method='CreateChannel')

    # bad handle
    ensure_error({cs.TARGET_HANDLE: 42})

    # offline
    ensure_error({cs.TARGET_ID: 'lolbags@dingdong'})

    props.update({cs.TARGET_HANDLE: handle})

    # RequestType
    ensure_error()
    ensure_error({ycs.REQUEST_TYPE: 99})
    props.update({ycs.REQUEST_TYPE: ycs.REQUEST_TYPE_GET})

    # TargetService
    ensure_error()
    ensure_error({ycs.TARGET_SERVICE: 'lol/bags/what\'s this?!!!!'})
    props.update({ycs.TARGET_SERVICE: 'the.target.service'})

    # InitiatorService
    ensure_error()
    ensure_error({ycs.INITIATOR_SERVICE: 'lol/bags/what\'s this?!!!!'})
    props.update({ycs.INITIATOR_SERVICE: 'the.initiator.service'})

    # RequestAttributes: a{ss}, not a{si}
    ensure_error({ycs.REQUEST_ATTRIBUTES: {'lol': 2}})

    # RequestBody
    ensure_error({ycs.REQUEST_BODY: 'no way is this real XML'})

def setup_incoming_tests(q, bus, conn, stream):
    handle, bare_jid, full_jid = setup_tests(q, bus, conn, stream)

    self_handle = conn.GetSelfHandle()
    self_handle_name =  conn.InspectHandles(cs.HT_CONTACT, [self_handle])[0]

    iq = IQ(None, 'get')
    iq['id'] = 'le-loldongs'
    iq['from'] = full_jid
    iq['to'] = self_handle_name
    msg = iq.addElement((ycs.MESSAGE_NS, 'message'))
    msg['from-service'] = 'the.from.service'
    msg['to-service'] = 'the.to.service'
    msg['owl-companions'] = 'the pussy cat'
    msg['destination'] = 'sea'
    msg['seacraft'] = 'beautiful pea green boat'

    lol = msg.addElement((None, 'lol'))
    lol['some'] = 'stuff'
    lol['to'] = 'fill'
    lol['the'] = 'time'
    lol.addElement((None, 'look-into-my-eyes'),
                   content='and tell me how boring writing these tests is')

    stream.send(iq)

    e = q.expect('dbus-signal', signal='NewChannels', predicate=lambda e:
                     e.args[0][0][1][cs.CHANNEL_TYPE] == ycs.CHANNEL_IFACE)
    path, props = e.args[0][0]

    assertEquals(handle, props[cs.INITIATOR_HANDLE])
    assertEquals(bare_jid, props[cs.INITIATOR_ID])
    assertEquals(False, props[cs.REQUESTED])
    assertEquals(handle, props[cs.TARGET_HANDLE])
    assertEquals(cs.HT_CONTACT, props[cs.TARGET_HANDLE_TYPE])
    assertEquals(bare_jid, props[cs.TARGET_ID])

    assertEquals('the.from.service', props[ycs.INITIATOR_SERVICE])
    assertEquals('the.to.service', props[ycs.TARGET_SERVICE])
    assertEquals(ycs.REQUEST_TYPE_GET, props[ycs.REQUEST_TYPE])
    assertEquals({'destination': 'sea',
                  'owl-companions': 'the pussy cat',
                  'seacraft': 'beautiful pea green boat'},
                 props[ycs.REQUEST_ATTRIBUTES])

    assertEquals('<?xml version="1.0" encoding="UTF-8"?>\n' \
                     '<message seacraft="beautiful pea green boat" ' \
                     'from-service="the.from.service" destination="sea" ' \
                     'owl-companions="the pussy cat" to-service="the.to.service" ' \
                     'xmlns="urn:ytstenut:message">' \
                     '<lol to="fill" the="time" some="stuff">' \
                     '<look-into-my-eyes>and tell me how boring ' \
                     'writing these tests is</look-into-my-eyes>' \
                     '</lol></message>\n', props[ycs.REQUEST_BODY])

    # finally we have our channel
    chan = wrap_channel(bus, conn, path)

    # let's check we can't call Request()
    call_async(q, chan, 'Request')
    q.expect('dbus-error', method='Request')

    return chan, bare_jid, full_jid, self_handle_name

def incoming_reply(q, bus, conn, stream):
    chan, bare_jid, full_jid, self_handle_name = \
        setup_incoming_tests(q, bus, conn, stream)

    moar = Element((ycs.MESSAGE_NS, 'message'))
    moar['ninety-nine-problems'] = 'but a sauvignon blanc aint one'
    moar['also'] = 'my mum said hi'
    trollface = moar.addElement('trollface', content='problem?')

    call_async(q, chan, 'Reply',
               {'ninety-nine-problems': 'but a sauvignon blanc aint one',
                'also': 'my mum said hi'},
               moar.toXml())

    _, e = q.expect_many(EventPattern('dbus-return', method='Reply'),
                         EventPattern('stream-message'))

    iq = e.stanza
    assertEquals('le-loldongs', iq['id'])
    assertEquals('result', iq['type'])
    assertEquals(self_handle_name, iq['from'])
    assertEquals(full_jid, iq['to'])
    assertEquals(1, len(iq.children))

    message = iq.children[0]

    assertEquals('message', message.name)
    assertEquals(ycs.MESSAGE_NS, message.uri)
    assertEquals('my mum said hi', message['also'])
    assertEquals('but a sauvignon blanc aint one', message['ninety-nine-problems'])
    assertEquals('the.from.service', message['to-service'])
    assertEquals('the.to.service', message['from-service'])
    assertEquals(1, len(message.children))

    trollface = message.children[0]

    assertEquals('trollface', trollface.name)
    assertEquals(1, len(trollface.children))

    assertEquals('problem?', trollface.children[0])

    # check we can't call anything any more
    call_async(q, chan, 'Fail', ycs.ERROR_TYPE_CANCEL, 'lol', 'whut', 'pear')
    q.expect('dbus-error', method='Fail')

    call_async(q, chan, 'Reply', {'lol':'whut'}, '')
    q.expect('dbus-error', method='Reply')

    call_async(q, chan, 'Request')
    q.expect('dbus-error', method='Request')

def incoming_fail(q, bus, conn, stream):
    chan, bare_jid, full_jid, self_handle_name = \
        setup_incoming_tests(q, bus, conn, stream)

    call_async(q, chan, 'Fail',
               ycs.ERROR_TYPE_AUTH, 'auth', 'omgwtfbbq',
               'I most certainly dont feel like dancing')

    _, e = q.expect_many(EventPattern('dbus-return', method='Fail'),
                         EventPattern('stream-message'))

    iq = e.stanza
    assertEquals('le-loldongs', iq['id'])
    assertEquals('error', iq['type'])
    assertEquals(self_handle_name, iq['from'])
    assertEquals(full_jid, iq['to'])
    assertEquals(2, len(iq.children))

    def check_message(message):
        assertEquals('message', message.name)
        assertEquals(ycs.MESSAGE_NS, message.uri)
        assertEquals('beautiful pea green boat', message['seacraft'])
        assertEquals('sea', message['destination'])
        assertEquals('the pussy cat', message['owl-companions'])
        assertEquals('the.from.service', message['from-service'])
        assertEquals('the.to.service', message['to-service'])
        assertEquals(1, len(message.children))

        lol = message.children[0]

        assertEquals('lol', lol.name)
        assertEquals('fill', lol['to'])
        assertEquals('time', lol['the'])
        assertEquals('stuff', lol['some'])
        assertEquals(1, len(lol.children))

        look = lol.children[0]

        assertEquals('look-into-my-eyes', look.name)
        assertEquals(1, len(look.children))
        assertEquals('and tell me how boring writing these tests is', look.children[0])

    def check_error(error):
        assertEquals('error', error.name)
        assertEquals('auth', error['type'])
        assertEquals(3, len(error.children))

        for c in error.children:
            if c.name == 'auth':
                assertEquals(ns.STANZA, c.uri)
            elif c.name == 'omgwtfbbq':
                assertEquals(ycs.MESSAGE_NS, c.uri)
            elif c.name == 'text':
                assertEquals(ns.STANZA, c.uri)
                assertEquals(1, len(c.children))
                assertEquals('I most certainly dont feel like dancing',
                             c.children[0])
            else:
                raise

    for child in iq.children:
        if child.name == 'message':
            check_message(child)
        elif child.name == 'error':
            check_error(child)
        else:
            raise

    # check we can't call anything any more
    call_async(q, chan, 'Fail', ycs.ERROR_TYPE_CANCEL, 'lol', 'whut', 'pear')
    q.expect('dbus-error', method='Fail')

    call_async(q, chan, 'Reply', {'lol':'whut'}, '')
    q.expect('dbus-error', method='Reply')

    call_async(q, chan, 'Request')
    q.expect('dbus-error', method='Request')

if __name__ == '__main__':
    exec_test(outgoing_reply)
    exec_test(outgoing_fail)
    exec_test(bad_requests)
    exec_test(incoming_reply)
    exec_test(incoming_fail)
