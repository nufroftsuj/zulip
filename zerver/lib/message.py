from __future__ import absolute_import

import datetime
import ujson
import zlib

from six import binary_type, text_type

from zerver.lib.avatar import get_avatar_url
from zerver.lib.avatar_hash import gravatar_hash
import zerver.lib.bugdown as bugdown
from zerver.lib.cache import cache_with_key, to_dict_cache_key
from zerver.lib.str_utils import force_bytes, dict_with_str_keys
from zerver.lib.timestamp import datetime_to_timestamp

from zerver.models import (
    get_display_recipient_by_id,
    Message,
    Recipient,
)

from typing import Any, Dict, Optional

def extract_message_dict(message_bytes):
    # type: (binary_type) -> Dict[str, Any]
    return dict_with_str_keys(ujson.loads(zlib.decompress(message_bytes).decode("utf-8")))

def stringify_message_dict(message_dict):
    # type: (Dict[str, Any]) -> binary_type
    return zlib.compress(force_bytes(ujson.dumps(message_dict)))

def message_to_dict(message, apply_markdown):
    # type: (Message, bool) -> Dict[str, Any]
    json = message_to_dict_json(message, apply_markdown)
    return extract_message_dict(json)

@cache_with_key(to_dict_cache_key, timeout=3600*24)
def message_to_dict_json(message, apply_markdown):
    # type: (Message, bool) -> binary_type
    return MessageDict.to_dict_uncached(message, apply_markdown)

class MessageDict(object):
    @staticmethod
    def to_dict_uncached(message, apply_markdown):
        # type: (Message, bool) -> binary_type
        dct = MessageDict.to_dict_uncached_helper(message, apply_markdown)
        return stringify_message_dict(dct)

    @staticmethod
    def to_dict_uncached_helper(message, apply_markdown):
        # type: (Message, bool) -> Dict[str, Any]
        return MessageDict.build_message_dict(
                apply_markdown = apply_markdown,
                message = message,
                message_id = message.id,
                last_edit_time = message.last_edit_time,
                edit_history = message.edit_history,
                content = message.content,
                subject = message.subject,
                pub_date = message.pub_date,
                rendered_content = message.rendered_content,
                rendered_content_version = message.rendered_content_version,
                sender_id = message.sender.id,
                sender_email = message.sender.email,
                sender_realm_domain = message.sender.realm.domain,
                sender_full_name = message.sender.full_name,
                sender_short_name = message.sender.short_name,
                sender_avatar_source = message.sender.avatar_source,
                sender_is_mirror_dummy = message.sender.is_mirror_dummy,
                sending_client_name = message.sending_client.name,
                recipient_id = message.recipient.id,
                recipient_type = message.recipient.type,
                recipient_type_id = message.recipient.type_id,
        )

    @staticmethod
    def build_dict_from_raw_db_row(row, apply_markdown):
        # type: (Dict[str, Any], bool) -> Dict[str, Any]
        '''
        row is a row from a .values() call, and it needs to have
        all the relevant fields populated
        '''
        return MessageDict.build_message_dict(
                apply_markdown = apply_markdown,
                message = None,
                message_id = row['id'],
                last_edit_time = row['last_edit_time'],
                edit_history = row['edit_history'],
                content = row['content'],
                subject = row['subject'],
                pub_date = row['pub_date'],
                rendered_content = row['rendered_content'],
                rendered_content_version = row['rendered_content_version'],
                sender_id = row['sender_id'],
                sender_email = row['sender__email'],
                sender_realm_domain = row['sender__realm__domain'],
                sender_full_name = row['sender__full_name'],
                sender_short_name = row['sender__short_name'],
                sender_avatar_source = row['sender__avatar_source'],
                sender_is_mirror_dummy = row['sender__is_mirror_dummy'],
                sending_client_name = row['sending_client__name'],
                recipient_id = row['recipient_id'],
                recipient_type = row['recipient__type'],
                recipient_type_id = row['recipient__type_id'],
        )

    @staticmethod
    def build_message_dict(
            apply_markdown,
            message,
            message_id,
            last_edit_time,
            edit_history,
            content,
            subject,
            pub_date,
            rendered_content,
            rendered_content_version,
            sender_id,
            sender_email,
            sender_realm_domain,
            sender_full_name,
            sender_short_name,
            sender_avatar_source,
            sender_is_mirror_dummy,
            sending_client_name,
            recipient_id,
            recipient_type,
            recipient_type_id,
    ):
        # type: (bool, Message, int, datetime.datetime, text_type, text_type, text_type, datetime.datetime, text_type, Optional[int], int, text_type, text_type, text_type, text_type, text_type, bool, text_type, int, int, int) -> Dict[str, Any]

        avatar_url = get_avatar_url(sender_avatar_source, sender_email)

        display_recipient = get_display_recipient_by_id(
                recipient_id,
                recipient_type,
                recipient_type_id
        )

        if recipient_type == Recipient.STREAM:
            display_type = "stream"
        elif recipient_type in (Recipient.HUDDLE, Recipient.PERSONAL):
            assert not isinstance(display_recipient, text_type)
            display_type = "private"
            if len(display_recipient) == 1:
                # add the sender in if this isn't a message between
                # someone and his self, preserving ordering
                recip = {'email': sender_email,
                         'domain': sender_realm_domain,
                         'full_name': sender_full_name,
                         'short_name': sender_short_name,
                         'id': sender_id,
                         'is_mirror_dummy': sender_is_mirror_dummy}
                if recip['email'] < display_recipient[0]['email']:
                    display_recipient = [recip, display_recipient[0]]
                elif recip['email'] > display_recipient[0]['email']:
                    display_recipient = [display_recipient[0], recip]

        obj = dict(
            id                = message_id,
            sender_email      = sender_email,
            sender_full_name  = sender_full_name,
            sender_short_name = sender_short_name,
            sender_domain     = sender_realm_domain,
            sender_id         = sender_id,
            type              = display_type,
            display_recipient = display_recipient,
            recipient_id      = recipient_id,
            subject           = subject,
            timestamp         = datetime_to_timestamp(pub_date),
            gravatar_hash     = gravatar_hash(sender_email), # Deprecated June 2013
            avatar_url        = avatar_url,
            client            = sending_client_name)

        obj['subject_links'] = bugdown.subject_links(sender_realm_domain.lower(), subject)

        if last_edit_time != None:
            obj['last_edit_timestamp'] = datetime_to_timestamp(last_edit_time)
            obj['edit_history'] = ujson.loads(edit_history)

        if apply_markdown:
            if Message.need_to_render_content(rendered_content, rendered_content_version, bugdown.version):
                if message is None:
                    # We really shouldn't be rendering objects in this method, but there is
                    # a scenario where we upgrade the version of bugdown and fail to run
                    # management commands to re-render historical messages, and then we
                    # need to have side effects.  This method is optimized to not need full
                    # blown ORM objects, but the bugdown renderer is unfortunately highly
                    # coupled to Message, and we also need to persist the new rendered content.
                    # If we don't have a message object passed in, we get one here.  The cost
                    # of going to the DB here should be overshadowed by the cost of rendering
                    # and updating the row.
                    # TODO: see #1379 to eliminate bugdown dependencies
                    message = Message.objects.select_related().get(id=message_id)

                # It's unfortunate that we need to have side effects on the message
                # in some cases.
                rendered_content = message.render_markdown(content, sender_realm_domain)
                message.rendered_content = rendered_content
                message.rendered_content_version = bugdown.version
                message.save_rendered_content()

            if rendered_content is not None:
                obj['content'] = rendered_content
            else:
                obj['content'] = u'<p>[Zulip note: Sorry, we could not understand the formatting of your message]</p>'

            obj['content_type'] = 'text/html'
        else:
            obj['content'] = content
            obj['content_type'] = 'text/x-markdown'

        return obj

def re_render_content_for_management_command(message):
    # type: (Message) -> None

    '''
    Please avoid using this function, as its only used in a management command that
    is somewhat deprecated.
    '''
    assert Message.need_to_render_content(message.rendered_content,
                                          message.rendered_content_version,
                                          bugdown.version)

    rendered_content = message.render_markdown(message.content)
    message.rendered_content = rendered_content
    message.rendered_content_version = bugdown.version
    message.save_rendered_content()
