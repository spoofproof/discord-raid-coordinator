import asyncio
import discord
import json
import sys
import time
import pytz
from datetime import datetime, timedelta, timezone

"""
Permission Requirements:

    - Manage Message and Read Message on the Announcement Channel
    - Mannage Channel, Manage Permissions / Roles and Read Message on the Raid Channels
"""


settings_path = "settings.json" if len(sys.argv) == 1 else sys.argv[1]
settings = json.load(open(settings_path, "rt"))

client = discord.Client()

def get_raid_channels(server):
    """Gets the list of raid channels for ther server."""
    return (c for c in server.channels if c.name.startswith('raid-group') and c.permissions_for(server.me).manage_roles)


def get_announcement_channel(server):
    """Gets the announcement channel for a server."""
    return discord.utils.find(lambda c: c.name == settings['announcement_channel'], server.channels)


def get_backup_channel(server):
    """Gets the announcement channel for a server."""
    return discord.utils.find(lambda c: c.name == settings['backup_raid_channel'], server.channels)


def get_raid_starting_embed(text):
    embed = discord.Embed()
    embed.title = "Starting raid group..."
    embed.description = text
    return embed


def get_raid_start_embed(creator_str, channel, text=None):
    embed = discord.Embed()
    embed.title = 'A raid has started!'
    if text:
        embed.description = text
    embed.color = discord.Color.green()
    embed.add_field(name='creator', value=creator_str, inline=True)
    embed.add_field(name='channel', value=channel.mention, inline=True)
    embed.set_footer(text='To join, tap {} below'.format(get_join_emoji()))
    return embed


def get_raid_end_embed(channel):
    embed = discord.Embed()
    embed.title = 'This raid has ended'
    embed.color = discord.Color.magenta()
    return embed


def get_raid_busy_embed(channel):
    embed = discord.Embed()
    embed.title = 'All raid channels are busy at the moment.'
    embed.description = 'Coordinate this raid in {} instead. More channels will be available later.'.format(channel.mention)
    embed.color = discord.Color.dark_teal()
    return embed


def get_raid_join_embed(user, channel):
    embed = discord.Embed()
    embed.description = '{} has joined the raid!'.format(user.mention)
    embed.color = discord.Color.green()
    return embed


def get_raid_left_embed(user, channel):
    embed = discord.Embed()
    embed.description = '{} has the left raid!'.format(user.mention)
    embed.color = discord.Color.red()
    return embed


def get_raid_members_embed(members):
    embed = discord.Embed()
    embed.title = "Raid Members ({})".format(len(members))
    embed.description = "\n".join(sorted(member.name for member in members))
    embed.color = discord.Color.green()
    return embed


def get_raid_summary_embed(creator, expiration_dt):
    embed = discord.Embed()
    embed.title = 'Welcome to the this raid channel!'
    embed.add_field(name='creator', value=creator.mention)
    embed.add_field(name='channel expires', value=expiration_dt.strftime("%Y-%m-%d %I:%M:%S %p"))
    embed.add_field(name="commands", value="You can use the following commands:", inline=False)
    embed.add_field(name="$leaveraid", value="Removes you from this raid.", inline=False)
    embed.add_field(name="$listraid", value="Shows all current members of this raid channel.", inline=False)
    embed.set_footer(text='You can also leave the raid with the {} reaction below.'.format(get_leave_emoji()))
    embed.color = discord.Color.green()
    return embed


def get_leave_emoji():
    """Gets the join emoji for a server."""
    return "\U0001F6AA"

def get_join_emoji():
    """Gets the join emoji for a server."""
    return "\U0001F464"


def is_raid_start_message(message):
    """Whether this is the start of a new raid."""
    if message.role_mentions:
        return any(mention.name.startswith('raid-') for mention in message.role_mentions)


def is_announcement_channel(channel):
    """Whether the channel is the announcement channel."""
    return channel and channel == get_announcement_channel(channel.server)


def is_raid_channel(channel):
    """Whether the channel is a valid raid_channel.
    """
    return channel and channel in get_raid_channels(channel.server)


async def update_raid_announcement(raid_channel, creator=None, text=None):
    """Updates the raid announcement for the raid channel."""
    message = await get_announcement_message(raid_channel)
    if message.embeds:
        embed = message.embeds[0]

        # find the creator
        if 'fields' in embed:
            creator = message.embeds[0]['fields'][0]['value']

        if 'description' in embed:
            text = embed['description']

    await client.edit_message(message, embed=get_raid_start_embed(creator, raid_channel, text=text))


def is_open(channel):
    return channel.topic is None


async def get_announcement_message(raid_channel):
    """Gets the message that created this channel."""
    server = raid_channel.server
    announcement_channel = get_announcement_channel(server)
    message_id = raid_channel.topic
    try:
        message = await client.get_message(announcement_channel, message_id)
    except:
        return None  # an error occurred, return None TODO: log here
    return message


def get_raid_channel(message):
    """Pulls out the channel field from the message embed."""
    if message.embeds:
        embed = message.embeds[0]
        channel_mention = embed['fields'][1]['value']
        for channel in get_raid_channels(message.channel.server):
            if channel.mention == channel_mention:
                return channel


async def is_raid_expired(raid_channel):
    message = await get_announcement_message(raid_channel)
    if message is None:
        return True  # can't find message, clean up the raid channel
    create_ts = message.timestamp.replace(tzinfo=timezone.utc).timestamp()
    return settings['raid_group_duration_seconds'] < time.time() - create_ts


def get_available_raid_channel(server):
    """We may need to wrap function calls to this in a lock."""
    for channel in get_raid_channels(server):
        if is_open(channel):
            return channel


async def start_raid_group(user, message_id):
    # get the server
    server = user.server

    # find an available raid channel
    channel = get_available_raid_channel(server)

    if channel:
        # set the topic
        await client.edit_channel(channel, topic=message_id)

        # get the message
        announcement_channel = get_announcement_channel(server)
        message = await client.get_message(announcement_channel, message_id)

        # calculate expiration time
        expiration_dt = message.timestamp + timedelta(seconds=settings['raid_group_duration_seconds'])
        zone = pytz.timezone('US/Eastern')
        expiration_dt = expiration_dt + zone.utcoffset(expiration_dt)
        summary_message = await client.send_message(channel, embed=get_raid_summary_embed(user, expiration_dt))

        # add shortcut reactions for commands
        await client.add_reaction(summary_message, get_leave_emoji())

        return channel

async def end_raid_group(channel):
    # remove all the permissions
    for target, _ in channel.overwrites:
        if isinstance(target, discord.User):
            await client.delete_channel_permissions(channel, target)

    # purge all messages
    await client.purge_from(channel)

    # update the message if its available
    message = await get_announcement_message(channel)
    if message:
        await client.edit_message(message, embed=get_raid_end_embed(channel))
        await client.clear_reactions(message)

    # remove the topic
    channel = await client.edit_channel(channel, topic=None)


def num_members_in_raid(channel):
    return sum(1 for target, _ in channel.overwrites if isinstance(target, discord.User))


async def invite_user_to_raid(channel, user):
    # adds an overwrite for the user
    perms = discord.PermissionOverwrite(read_messages=True)
    await client.edit_channel_permissions(channel, user, perms)

    # sends a message to the raid channel the user was added
    await client.send_message(channel, embed=get_raid_join_embed(user, channel))

    # update the member announcement message member count
    await update_raid_announcement(channel, user.mention)


async def uninvite_user_from_raid(channel, user):
    # reflect the proper number of members (the bot role and everyone are excluded)
    await client.delete_channel_permissions(channel, user)
    await client.send_message(channel, embed=get_raid_left_embed(user, channel))

    # remove the messages emoji
    server = channel.server
    announcement_message = await get_announcement_message(channel)
    await client.remove_reaction(announcement_message, get_join_emoji(), user)

    # update the announcement message
    await update_raid_announcement(channel)


async def list_raid_members(channel):
    members = [target for target, _ in channel.overwrites if isinstance(target, discord.User)]
    await client.send_message(channel, embed=get_raid_members_embed(members))


async def cleanup_raid_channels():
    while True:
        for server in client.servers:
            channels = get_raid_channels(server)
            for channel in channels:
                if not is_open(channel):
                    expired = await is_raid_expired(channel)
                    if expired or not num_members_in_raid(channel):
                        await end_raid_group(channel)
        await asyncio.sleep(60)


@client.event
async def on_ready():
    print('Logged in as {}'.format(client.user.name))
    print('------')
    await cleanup_raid_channels()


@client.event
async def on_reaction_add(reaction, user):
    """Invites a user to a raid channel they react to they are no already there."""
    server = reaction.message.server
    announcement_channel = get_announcement_channel(server)
    if reaction.emoji == get_join_emoji() and announcement_channel == reaction.message.channel:
        message = reaction.message
        raid_channel = get_raid_channel(message)
        if is_raid_channel(raid_channel):
            # NB: use overwrites for, since admins otherwise won't be notified
            # we know the channel is private and only overwrites matter
            if raid_channel.overwrites_for(user).is_empty() and user != message.server.me:
                await invite_user_to_raid(raid_channel, user)

    elif reaction.emoji == get_leave_emoji():
        message = reaction.message
        raid_channel = message.channel
        if is_raid_channel(raid_channel):
            # NB: use overwrites for, since admins otherwise won't be notified
            # we know the channel is private and only overwrites matter
            if not raid_channel.overwrites_for(user).is_empty() and user != message.server.me:
                await uninvite_user_from_raid(raid_channel, user)

                # remove this reaction
                await client.remove_reaction(message, reaction.emoji, user)


@client.event
async def on_reaction_remove(reaction, user):
    """Uninvites a user to a raid when they remove a reaction if they are there."""
    server = reaction.message.server
    announcement_channel = get_announcement_channel(server)
    if reaction.emoji == get_join_emoji() and announcement_channel == reaction.message.channel:
        message = reaction.message
        raid_channel = get_raid_channel(message)
        if is_raid_channel(raid_channel):
            # NB: use overwrites for, since admins otherwise won't be notified
            # we know the channel is private and only overwrites matter
            if not raid_channel.overwrites_for(user).is_empty() and user != message.server.me:
                await uninvite_user_from_raid(raid_channel, user)

@client.event
async def on_message(message):
    # we'll need this for future
    server = message.server
    channel = message.channel
    user = message.author
    if is_announcement_channel(channel) and is_raid_start_message(message):
        # send the message, then edit the raid to avoid a double notification
        raid_message = await client.send_message(channel, embed=get_raid_starting_embed(""))
        raid_message = await client.edit_message(raid_message, embed=get_raid_starting_embed(message.content))
        raid_channel = await start_raid_group(user, raid_message.id)
        if raid_channel:
            # invte the member
            await invite_user_to_raid(raid_channel, user)

            # add a join reaction to the message
            join_emoji = get_join_emoji()
            await client.add_reaction(raid_message, join_emoji)
        else:
            # notify them to use the backup raid channel, this won't be monitored
            backup_channel = get_backup_channel(server)
            #content = 'Unable to start a dedicated raid channel, all available channels are full. Please coordinate this raid in the {} channel'.format(backup_channel.mention)
            m = await client.edit_message(raid_message, embed=get_raid_busy_embed(backup_channel))
            await client.add_reaction(m, '\U0001F61F')  # frowning
    elif is_raid_channel(channel) and message.content.startswith('$leaveraid'):
        await uninvite_user_from_raid(channel, user)
    elif is_raid_channel(channel) and message.content.startswith('$listraid'):
        await list_raid_members(channel)


client.run(settings['token'])
