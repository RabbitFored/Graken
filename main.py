import os
import pyromod
from pyrogram import Client,filters,utils, raw,idle
import base64
from Crypto.Cipher import AES
from aiohttp import web
import logging
import math
from pyrogram.file_id import FileId, FileType, ThumbnailSource
from pyrogram.session import Session, Auth
from pyrogram.errors import AuthBytesInvalid
from typing import Union
from pyrogram.types import Message
import secrets
import mimetypes
import asyncio
import pymongo
import time
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import UserNotParticipant
from tenacity import *
import requests
from pyrogram.types import ForceReply
import json
import aiohttp
import aiofiles
import database
import youtube_dl
from aioftp.errors import StatusCodeError
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive
from bs4 import BeautifulSoup
import tldextract
import cloudscraper
from cloudscraper.exceptions import CloudflareChallengeError
import aioftp
import pyromod.listen

sudoers = []
for i in os.environ.get("sudoers").split(" "):
  sudoers.append(int(i))
  
routes = web.RouteTableDef()
async def web_server():
    web_app = web.Application(client_max_size=30000000)
    web_app.add_routes(routes)
    return web_app

team_drive_id = os.environ['team_drive_id']
parent_folder_id =os.environ['parent_folder_id']

ostrich = Client("theostrich",
        bot_token=os.environ['bot_token'],
       api_id=os.environ['api_id'],
        api_hash=os.environ['api_hash'])


key = os.environ['key']
iv = os.environ['iv']

myclient = pymongo.MongoClient(
        os.environ['mongouri'])
db = myclient['graken']
collection = db["usercache"]


@ostrich.on_message(filters.command(["broadcast"]))
async def broadcast(client, message):
      chat_id = message.chat.id
      botOwnerID = [1775541139 ,1520625615]
      if chat_id in botOwnerID:
        await message.reply_text("Broadcasting...")
        chat = (collection.find({}, {'userid': 1, '_id': 0}))
        chats = [sub['userid'] for sub in chat]
        failed = 0
        for chat in chats:
          try:
              await message.reply_to_message.copy(chat)
              time.sleep(2)
          except:
                failed += 1
                print("Couldn't send broadcast to %s, group name %s", chat)
        await message.reply_text("Broadcast complete. {} users failed to receive the message, probably due to being kicked.".format(failed))
      else:
        await client.send_message(1520625615,f"Someone tried to access broadcast command,{chat_id}")


@routes.get("/")
async def welc(request):
    return web.Response(text="Graken - @theostrich")


@routes.get("/quantum/{message_id}")
async def stream_handler(request):
   
    try:
        message_id = request.match_info['message_id']
        if "." in message_id:
            message_id = message_id.split(".")[0]
        decodedBytes = base64.urlsafe_b64decode(message_id)
        decryption_suite = AES.new(key.encode("utf8"), AES.MODE_CFB, iv.encode("utf8"))
        file_id = decryption_suite.decrypt(decodedBytes)
        return await media_streamer(request, int(file_id))
    except ValueError as e:
        logging.error(e)
        raise web.HTTPNotFound

async def chunk_size(length):
    return 2 ** max(min(math.ceil(math.log2(length / 1024)), 10), 2) * 1024
async def offset_fix(offset, chunksize):
    offset -= offset % chunksize
    return offset


async def media_streamer(request, message_id: int):
    range_header = request.headers.get('Range', 0)
    media_msg = await ostrich.get_messages(-1001969387915, message_id)
    file_properties = await TGCustomYield().generate_file_properties(media_msg)
    file_size = file_properties.file_size

    if range_header:
        from_bytes, until_bytes = range_header.replace('bytes=', '').split('-')
        from_bytes = int(from_bytes)
        until_bytes = int(until_bytes) if until_bytes else file_size - 1
    else:
        from_bytes = request.http_range.start or 0
        until_bytes = request.http_range.stop or file_size - 1

    req_length = until_bytes - from_bytes

    new_chunk_size = await chunk_size(req_length)
    offset = await offset_fix(from_bytes, new_chunk_size)
    first_part_cut = from_bytes - offset
    last_part_cut = (until_bytes % new_chunk_size) + 1
    part_count = math.ceil(req_length / new_chunk_size)
    body = TGCustomYield().yield_file(media_msg, offset, first_part_cut, last_part_cut, part_count,
                                      new_chunk_size)

    file_name = file_properties.file_name if file_properties.file_name \
        else f"{secrets.token_hex(2)}.jpeg"
    mime_type = file_properties.mime_type if file_properties.mime_type \
        else f"{mimetypes.guess_type(file_name)}"

    return_resp = web.Response(
        status=206 if range_header else 200,
        body=body,
        headers={
            "Content-Type": mime_type,
            "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
            "Content-Disposition": f'attachment; filename="{file_name}"',
            "Accept-Ranges": "bytes",
        }
    )

    if return_resp.status == 200:
        return_resp.headers.add("Content-Length", str(file_size))

    return return_resp



class TGCustomYield:
    def __init__(self):
        """ A custom method to stream files from telegram.
        functions:
            generate_file_properties: returns the properties for a media on a specific message contained in FileId class.
            generate_media_session: returns the media session for the DC that contains the media file on the message.
            yield_file: yield a file from telegram servers for streaming.
        """
        self.main_bot = ostrich

    @staticmethod
    async def generate_file_properties(msg: Message):
        error_message = "This message doesn't contain any downloadable media"
        available_media = ("audio", "document", "photo", "sticker", "animation", "video", "voice", "video_note")

        if isinstance(msg, Message):
            for kind in available_media:
                media = getattr(msg, kind, None)

                if media is not None:
                    break
            else:
                raise ValueError(error_message)
        else:
            media = msg

        if isinstance(media, str):
            file_id_str = media
        else:
            file_id_str = media.file_id

        file_id_obj = FileId.decode(file_id_str)

        # The below lines are added to avoid a break in routes.py
        setattr(file_id_obj, "file_size", getattr(media, "file_size", 0))
        setattr(file_id_obj, "mime_type", getattr(media, "mime_type", ""))
        setattr(file_id_obj, "file_name", getattr(media, "file_name", ""))

        return file_id_obj

    async def generate_media_session(self, client: Client, msg: Message):
        data = await self.generate_file_properties(msg)

        media_session = client.media_sessions.get(data.dc_id, None)

        if media_session is None:
            if data.dc_id != await client.storage.dc_id():
                media_session = Session(
                    client, data.dc_id, await Auth(client, data.dc_id, await client.storage.test_mode()).create(),
                    await client.storage.test_mode(), is_media=True
                )
                await media_session.start()

                for _ in range(3):
                    exported_auth = await client.invoke(
                        raw.functions.auth.ExportAuthorization(
                            dc_id=data.dc_id
                        )
                    )

                    try:
                        await media_session.send(
                            raw.functions.auth.ImportAuthorization(
                                id=exported_auth.id,
                                bytes=exported_auth.bytes
                            )
                        )
                    except AuthBytesInvalid:
                        continue
                    else:
                        break
                else:
                    await media_session.stop()
                    raise AuthBytesInvalid
            else:
                media_session = Session(
                    client, data.dc_id, await client.storage.auth_key(),
                    await client.storage.test_mode(), is_media=True
                )
                await media_session.start()

            client.media_sessions[data.dc_id] = media_session

        return media_session

    @staticmethod
    async def get_location(file_id: FileId):
        file_type = file_id.file_type

        if file_type == FileType.CHAT_PHOTO:
            if file_id.chat_id > 0:
                peer = raw.types.InputPeerUser(
                    user_id=file_id.chat_id,
                    access_hash=file_id.chat_access_hash
                )
            else:
                if file_id.chat_access_hash == 0:
                    peer = raw.types.InputPeerChat(
                        chat_id=-file_id.chat_id
                    )
                else:
                    peer = raw.types.InputPeerChannel(
                        channel_id=utils.get_channel_id(file_id.chat_id),
                        access_hash=file_id.chat_access_hash
                    )

            location = raw.types.InputPeerPhotoFileLocation(
                peer=peer,
                volume_id=file_id.volume_id,
                local_id=file_id.local_id,
                big=file_id.thumbnail_source == ThumbnailSource.CHAT_PHOTO_BIG
            )
        elif file_type == FileType.PHOTO:
            location = raw.types.InputPhotoFileLocation(
                id=file_id.media_id,
                access_hash=file_id.access_hash,
                file_reference=file_id.file_reference,
                thumb_size=file_id.thumbnail_size
            )
        else:
            location = raw.types.InputDocumentFileLocation(
                id=file_id.media_id,
                access_hash=file_id.access_hash,
                file_reference=file_id.file_reference,
                thumb_size=file_id.thumbnail_size
            )

        return location

    async def yield_file(self, media_msg: Message, offset: int, first_part_cut: int,
                         last_part_cut: int, part_count: int, chunk_size: int) -> Union[str, None]: #pylint: disable=unsubscriptable-object
        client = self.main_bot
        data = await self.generate_file_properties(media_msg)
        media_session = await self.generate_media_session(client, media_msg)

        current_part = 1

        location = await self.get_location(data)

        r = await media_session.send(
            raw.functions.upload.GetFile(
                location=location,
                offset=offset,
                limit=chunk_size
            ),
        )

        if isinstance(r, raw.types.upload.File):
            while current_part <= part_count:
                chunk = r.bytes
                if not chunk:
                    break
                offset += chunk_size
                if part_count == 1:
                    yield chunk[first_part_cut:last_part_cut]
                    break
                if current_part == 1:
                    yield chunk[first_part_cut:]
                if 1 < current_part <= part_count:
                    yield chunk

                r = await media_session.send(
                    raw.functions.upload.GetFile(
                        location=location,
                        offset=offset,
                        limit=chunk_size
                    ),
                )

                current_part += 1

    async def download_as_bytesio(self, media_msg: Message):
        client = self.main_bot
        data = await self.generate_file_properties(media_msg)
        media_session = await self.generate_media_session(client, media_msg)

        location = await self.get_location(data)

        limit = 1024 * 1024
        offset = 0

        r = await media_session.send(
            raw.functions.upload.GetFile(
                location=location,
                offset=offset,
                limit=limit
            )
        )

        if isinstance(r, raw.types.upload.File):
            m_file = []
            # m_file.name = file_name
            while True:
                chunk = r.bytes

                if not chunk:
                    break

                m_file.append(chunk)

                offset += limit

                r = await media_session.send(
                    raw.functions.upload.GetFile(
                        location=location,
                        offset=offset,
                        limit=limit
                    )
                )

            return m_file


async def eosf(_, __, m):
   if not m.chat.id in sudoers:
     return True

eosfilter = filters.create(eosf)

@ostrich.on_message(eosfilter)
async def eos(client, message):
  await message.reply_text("**End Of Service :**\n\n__This bot is no longer for public use.__\n**Join @theostrich to find more useful bots.**")

async def pdisklink(_, __, m):
    pdisk = []
    if m.text:

     for entity in m.text.entities:
        if entity.type == "url":
            o = entity.offset
            l = entity.length
            url = m.text[o:o + l]

            reqs = requests.get(url)
            soup = BeautifulSoup(reqs.text, 'html.parser') 
            for titles in soup.find_all('title'): 
              title = titles.get_text()
              if "PDisk" in title:
                pdisk.append(m.text[o:o + l])
    return len(pdisk) > 0

pdisk_filter = filters.create(pdisklink)

async def anonlink(_, __, m):
    anon = []
    if m.text:

     for entity in m.text.entities:
        if entity.type == "url":
            o = entity.offset
            l = entity.length
            url = m.text[o:o + l]
            
            tld = tldextract.extract(url)
            domain = tld.domain + "." + tld.suffix

            if domain == "anonfiles.com":
              anon.append(url)

    return len(anon) > 0

anon_filter = filters.create(anonlink)

async def utubelink(_, __, m):
    utube = []
    if m.text:

     for entity in m.text.entities:
        if entity.type == "url":
            o = entity.offset
            l = entity.length
            url = m.text[o:o + l]
            
            tld = tldextract.extract(url)
            domain = tld.domain + "." + tld.suffix

            if domain == "youtube.com" or domain == "youtu.be":
              utube.append(url)

    return len(utube) > 0

utube_filter = filters.create(utubelink)

@ostrich.on_message(utube_filter)
async def utube(client, message):
    ydl = youtube_dl.YoutubeDL()
    utubelink = []
    for entity in message.text.entities:
        if entity.type == "url":
            o = entity.offset
            l = entity.length
            url = message.text[o:o + l]
            utubelink.append(url)
    
    links = []
    for url in utubelink:
      try:
        try:
            result = ydl.extract_info(url, download=False)
            link = result['url']
            links.append(link)
        except:
            with youtube_dl.YoutubeDL(dict(forceurl=True)) as ydl:
                r = ydl.extract_info(url, download=False)
                link = r['formats'][-1]['url']
                links.append(link)
      except:
        print("error")
    if len(links) == 0:
       await message.reply_text("**Cannot find Download links!\n\nProvide me some URL to get direct link\nEg:**\n\t\t`/utube https://www.youtube.com/watch?v=h6fcK_fRYaI`**")
       return
    text ="Direct download link:\n"

    for i in links:
         text = text + f"  - {i}\n"
        
    await message.reply_text(text, parse_mode=None)  


async def mediaflink(_, __, m):
    mlink = []
    if m.text:

     for entity in m.text.entities:
        if entity.type == "url":
            o = entity.offset
            l = entity.length
            url = m.text[o:o + l]
            
            tld = tldextract.extract(url)
            domain = tld.domain + "." + tld.suffix

            if domain == "mediafire.com":
              mlink.append(url)

    return len(mlink) > 0

mediafire_filter = filters.create(mediaflink)


async def onedrivelink(_, __, m):
    onelink = []
    if m.text:

     for entity in m.text.entities:
        if entity.type == "url":
            o = entity.offset
            l = entity.length
            url = m.text[o:o + l]
            
            tld = tldextract.extract(url)
            domain = tld.domain + "." + tld.suffix

            if domain == "1drv.ms":
              onelink.append(url)

    return len(onelink) > 0

onedrive_filter = filters.create(onedrivelink)



@ostrich.on_message(mediafire_filter)
async def mediafdirect(client, message):
    mlink = []
    for entity in message.text.entities:
        if entity.type == "url":
            o = entity.offset
            l = entity.length
            url = message.text[o:o + l]
            mlink.append(url)
    
    links = []
    for urls in mlink:
      try:
        link = extract_mf(urls)
        links.append(link)
      except:
        pass

    if len(links) == 0:
       await message.reply_text("**Cannot find Download links!**")
       return
    text ="**Direct download link:**\n"

    for i in links:
        text = text + f"  - {i}\n"
        
    await message.reply_text(text)   

def extract_mf(url):
    
    r = requests.get(url).text
    soup = BeautifulSoup(r, "html.parser")
    link = soup.find("a",{"id":"downloadButton"})['href']

    return link




@ostrich.on_message(onedrive_filter)
async def onedrivedirect(client, message):
    mlink = []
    for entity in message.text.entities:
        if entity.type == "url":
            o = entity.offset
            l = entity.length
            url = message.text[o:o + l]
            mlink.append(url)
    
    links = []
    for urls in mlink:
      #try:
        link = extract_1(urls)
        links.append(link)
     # except:
      #  pass

    if len(links) == 0:
       await message.reply_text("**Cannot find Download links!**")
       return
    text ="**Direct download link:**\n"

    for i in links:
        text = text + f"  - {i}\n"
        
    await message.reply_text(text)   


@ostrich.on_message(anon_filter)
async def anondirect(client, message):
    anon = []
    for entity in message.text.entities:
        if entity.type == "url":
            o = entity.offset
            l = entity.length
            url = message.text[o:o + l]
            anon.append(url)
    
    links = []
    for urls in anon:
        try:
            link = extract_anon(urls)
            links.append(link)
        except:
            print("Anon error")

    if len(links) == 0:
       await message.reply_text("**Cannot find Download links!**")
       return
    text ="**Direct download link:**\n"

    for i in links:
        text = text + f"  - {i}\n"
        
    await message.reply_text(text)   

def extract_anon(url):
      link = ""
      try:
          scraper = cloudscraper.create_scraper()
          website_content = scraper.get(url).text
          soup = BeautifulSoup(website_content, "html.parser") 
          link = soup.find("a", id="download-url")["href"]
      except CloudflareChallengeError:
         params = {
                 'access_key': 'f9e20e8cdbebb17005180ee2a3d67805',
                 'url': url,
                }

         api_result = requests.get('http://api.scrapestack.com/scrape', params)
         website_content = api_result.content
         soup = BeautifulSoup(website_content, "html.parser") 
         link = soup.find("a", id="download-url")["href"]

      return link


def extract_1(url):
    data_bytes64 = base64.b64encode(bytes(url, 'utf-8'))
    data_bytes64_String = data_bytes64.decode('utf-8').replace('/','_').replace('+','-').rstrip("=")
    link = f"https://api.onedrive.com/v1.0/shares/u!{data_bytes64_String}/root/content"
    return link


@ostrich.on_message(pdisk_filter)
async def pdisk(client, message):
    pdisk = []
    for entity in message.text.entities:
        if entity.type == "url":
            o = entity.offset
            l = entity.length
            url = message.text[o:o + l]

            reqs = requests.get(url)
            soup = BeautifulSoup(reqs.text, 'html.parser') 
            for titles in soup.find_all('title'): 
              title = titles.get_text()
              if "PDisk" in title:
                pdisk.append(message.text[o:o + l])
    
    links = []
    for url in pdisk:
      reqs = requests.get(url)
      soup = BeautifulSoup(reqs.text, 'html.parser') 
      video = soup.find("video")
      
      if not video: 
        continue
      
      links.append(video.source.attrs["src"])

    text ="**Direct download link:**\n"

    for i in links:
        text = text + f"  - {i}\n"
        
    await message.reply_text(text)   

async def gdrive(client, message):
          await message.reply_text(
        text=f'''**Choose an option:**''',
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("TEAM DRIVE", callback_data="gtdrive"),
                ],                [
                    InlineKeyboardButton("Personal Storage", callback_data="gpdrive"),
                ]
            ]
        ),
        reply_to_message_id=message.reply_to_message.id
    )
    
async def down(client, message):
      download_location = await client.download_media(message = media,progress=progress_func,
      progress_args=(
            "**Downloading your file to server...**",
            msg,
            c_time))
      c_time = time.time()
   #   try
         
           

async def gtdrive(client, message):

      
      media = message.reply_to_message
      msg = await client.send_message(chat_id=message.chat.id, text='**Downloading your file to my server...**',reply_markup=InlineKeyboardMarkup([
                                        [InlineKeyboardButton(text="Check Progress", callback_data="progress_msg")]
                                    ]))

                                    
                                
                                    
      c_time = time.time()

      try:
        download_location = await client.download_media(message = media,progress=progress_func,
          progress_args=(
            "**Downloading your file to server...**",
            msg,
            c_time))

      except:
          await msg.edit_text('Download failed.')
          return

      await msg.edit_text(text='Getting you a fast URL...')
      try:
        f = await gtupload(download_location)
        download_url = f['alternateLink']
        await msg.edit_text(text = f'**Click this to download your file:**\n\n{download_url}',
                          reply_markup=InlineKeyboardMarkup([
                              [InlineKeyboardButton(text="OPEN IN BROWSER", url =f'{download_url}')]
                          ])
                       ,disable_web_page_preview=True)

      except:
          await msg.edit_text(text='Something went wrong. Contact my developers @theostrich')      
      

      os.remove(download_location)

          

async def gpdrive(client, message):

      
      media = message.reply_to_message
      gauth = GoogleAuth()
      authurl = gauth.GetAuthUrl()
      token = await client.ask(message.chat.id, '**Authorize me to upload files to your personal drive\n\nOpen this authorization URL in your browser and send me the authorization token.**',                          reply_markup=InlineKeyboardMarkup([
                              [InlineKeyboardButton(text="Authorize", url =f'{authurl}')]
                          ]))
      msg = await client.send_message(chat_id=message.chat.id, text='**Downloading your file to my server...**',reply_markup=InlineKeyboardMarkup([
                                        [InlineKeyboardButton(text="Check Progress", callback_data="progress_msg")]
                                    ]))

                                    
                                
                                    
      c_time = time.time()

      try:
        download_location = await client.download_media(message = media,progress=progress_func,
          progress_args=(
            "**Downloading your file to server...**",
            msg,
            c_time))

      except:
          await msg.edit_text('Download failed.')
          return

      await msg.edit_text(text='Getting you a fast URL...')
      try:
        f = await gpupload(download_location,client,message,token.text)
        download_url = f['alternateLink']
        await msg.edit_text(text = f'**Click this to download your file:**\n\n{download_url}',
                          reply_markup=InlineKeyboardMarkup([
                              [InlineKeyboardButton(text="OPEN IN BROWSER", url =f'{download_url}')]
                          ])
                       ,disable_web_page_preview=True)

      except:
          await msg.edit_text(text='Something went wrong. Contact my developers @theostrich')      
      

      os.remove(download_location)

async def gtupload(path):

      filename = os.path.basename(path) 

      gauth = GoogleAuth()
      gauth.LoadCredentialsFile("secretauth")
        
      if gauth.access_token_expired:
        # Refresh them if expired
        gauth.Refresh()
        gauth.SaveCredentialsFile("secretauth")
        
      drive = GoogleDrive(gauth)
      

      http = drive.auth.Get_Http_Object()
      f = drive.CreateFile({
            'title': filename,
            'parents': [{
                'kind': 'drive#fileLink',
                'teamDriveId': team_drive_id,
                'id': parent_folder_id
    }]
})     
      f.SetContentFile(path)
      f.Upload(param={'supportsTeamDrives': True})
      return f
async def gpupload(path,client,message,token):

      filename = os.path.basename(path) 
      gauth = GoogleAuth()

      gauth.Auth(token)
      drive = GoogleDrive(gauth)

      http = drive.auth.Get_Http_Object()
      f = drive.CreateFile({
            'title': filename,
})     
      f.SetContentFile(path)
      f.Upload()
      return f
@ostrich.on_message(filters.command(["start"]))
async def start(client, message):
        await message.reply_text(
        text=f'''**
Hello {message.from_user.mention(style="md")} 👋 !

Are you feeling slow download speed? Don't worry. I can generate high-speed download links and store those files for you.

Check help to find out more about how to use me.**''',
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("HELP", callback_data="getHelp"),
                ]
            ]
        ),
        reply_to_message_id=message.id
    )
        database.scrape(message)
        

@ostrich.on_message(filters.command(["help"]))
async def assist(client, message):

    await message.reply_text(
        text=f"**Hi {message.chat.first_name}."
                 "\nHere is a detailed guide on using me."
                 "\n\nYou might have faced slow download speed while downloading telegram files."
                 "\n\nForward me any telegram file, and I will generate you a high-speed download link."
                 "\n\nFor further information and guidance, contact my developers at my support group.**",
                  disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("SUPPORT GROUP", url="https://t.me/ostrichdiscussion"),
                ]
            ]
        ),
        reply_to_message_id=message.id
    )






@ostrich.on_message(filters.private & (filters.document | filters.video))
async def download(client, message):
    media = message
    filetype = media.document or media.video
    freelimit = 1000000000000000000
    channellimit = 5000000000000000000000
    filesize = filetype.file_size
    if filesize < channellimit:
     if filesize < freelimit:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(text="Graken [ Recommended ]", callback_data="graken")],     
            [InlineKeyboardButton(text="Gofile", callback_data="gofile")],
            [InlineKeyboardButton(text="transfer.sh", callback_data="transfersh")],
            #[InlineKeyboardButton(text="oshi.at", callback_data="oshi")],
            [InlineKeyboardButton(text="Anon files", callback_data="anon_files")],
            [InlineKeyboardButton(text="Google Drive", callback_data="gdrive")],
            [InlineKeyboardButton(text="ftp", callback_data="ftp")],
            [InlineKeyboardButton(text="MORE PLATFORMS", callback_data="next_1")]
                    ])
        await message.reply_text("**Select a Platform:**", quote=True, reply_markup=keyboard)
     else:
        try:
            user = await client.get_chat_member('theostrich', message.chat.id)
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(text="Graken [ Recommended ]", callback_data="graken")],
                [InlineKeyboardButton(text="Gofile", callback_data="gofile")],
                [InlineKeyboardButton(text="transfer.sh", callback_data="transfersh")],
                #[InlineKeyboardButton(text="oshi.at", callback_data="oshi")],
                [InlineKeyboardButton(text="Anon files", callback_data="anon_files")],
                [InlineKeyboardButton(text="Google Drive", callback_data="gdrive")],
                [InlineKeyboardButton(text="ftp", callback_data="ftp")],
                [InlineKeyboardButton(text="MORE PLATFORMS", callback_data="next_1")]


            ])
            await message.reply_text("**Select a Platform:**", quote=True, reply_markup=keyboard)
        except UserNotParticipant:
            await message.reply_text(
                text="**Due to limited resource, files greater than 100mb require channel membership.**",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(text="Join theostrich", url=f"https://t.me/theostrich")]
              ])
            )
    else:
      await message.reply_text(
                text="**Due to limited resource, free users cannot upload files more than 500mb.**",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(text="Join theostrich", url=f"https://t.me/theostrich")]
              ])
            )



async def doodstream(client, message):
      forwarded = await message.reply_to_message.forward(-1001461089993)
      file_id = forwarded.message_id

      encrypted_id = encrypt_id(file_id)
      
      url = f"http://graken.themails.ml/{encrypted_id}"

      r = requests.get(f"https://doodapi.com/api/upload/url?key=49155jrrhijk3niut342v&url={url}")

      res = json.loads(r.text)
      file_code = res['result']['filecode']

      download_url = f"https://doodstream.com/d/{file_code}"
      await message.reply_text(text = f'''**
This platform is not suggested to download files. 

<< THIS MAY CONTAIN INAPROPRIATE ADS >>

Click this to download your file:**\n\n{download_url}

[ This link may take some time load based on your file size]
''',
                          reply_markup=InlineKeyboardMarkup([
                              [InlineKeyboardButton(text="OPEN IN BROWSER", url =f'{download_url}')]
                          ])
                          ,disable_web_page_preview=True)


async def pdisk(client, message):
      forwarded = await message.reply_to_message.forward(-1001461089993)
      file_id = forwarded.id

      encrypted_id = encrypt_id(file_id)
      
      url = f"http://graken.themails.ml/{encrypted_id}"

     

      r = requests.get(f"https://pdisk.net/api/ndisk_manager/video/create?link_type=link&content_src={url}&source=2000&uid=17033242&title=graken&description=Uploaded by @grakenBot")

      res = json.loads(r.text)
      file_code = res['data']['item_id']

      download_url = f"https://www.pdisk.net/share-video?videoid={file_code}"
      await message.reply_text(text = f'''**
This platform is not suggested to download files. 

<< THIS MAY CONTAIN INAPROPRIATE ADS >>

Click this to download your file:**\n\n{download_url}

[ This link may take some time load based on your file size]
''',
                          reply_markup=InlineKeyboardMarkup([
                              [InlineKeyboardButton(text="OPEN IN BROWSER", url =f'{download_url}')]
                          ])
                          ,disable_web_page_preview=True)



async def anonfiles(client, message):

      media = message.reply_to_message
      msg = await client.send_message(chat_id=message.chat.id, text='**Downloading your file to my server...**',reply_markup=InlineKeyboardMarkup([
                                        [InlineKeyboardButton(text="Check Progress", callback_data="progress_msg")]
                                    ]))
                                    
                                    
                                    
                                    
      c_time = time.time()
      try:
        download_location = await client.download_media(message = media,progress=progress_func,
        progress_args=(
            "**Downloading your file to server...**",
            msg,
            c_time))
      except:
          msg.edit_text('Retrying Download, Please wait')
          download_location = await client.download_media(message=media)

      await msg.edit_text(text='Getting you a fast URL...')
      try:
        async with aiohttp.ClientSession() as session:
            files = {
                'file': open(download_location, 'rb')
            }
            request = await session.post("https://api.anonfiles.com/upload", data=files)

      except:
          await msg.edit_text(text='Something went wrong. Contact my developers @theostrich')
      json_response = await request.json()
      download_url = json_response["data"]["file"]["url"]["full"]
      
      
      await msg.edit_text(text = f'**Click this to download your file:**\n\n{download_url}',
                          reply_markup=InlineKeyboardMarkup([
                              [InlineKeyboardButton(text="OPEN IN BROWSER", url =f'{download_url}')]
                          ])
                          ,disable_web_page_preview=True)

      os.remove(download_location)
      


      
      
async def upftp(client, message):

      media = message.reply_to_message
      HOSTNAME = await client.ask(message.chat.id, '''**Enter ftp hostname.
Eg: `ftp.dlptest.com`
''',reply_markup=ForceReply())
      USERNAME = await client.ask(message.chat.id, '''**Enter ftp username.
Eg: `dlpuser`
''',reply_markup=ForceReply())
      PASSWORD = await client.ask(message.chat.id, '''**Enter ftp password.
Eg: `rNrKYTX9g7z3RgJRmxWuGHbeu`
''',reply_markup=ForceReply())

      msg = await client.send_message(chat_id=message.chat.id, text='**Downloading your file to my server...**',reply_markup=InlineKeyboardMarkup([
                                        [InlineKeyboardButton(text="Check Progress", callback_data="progress_msg")]
                                    ]))
                                    
                                    
                                    
                                    
      c_time = time.time()
      try:
        download_location = await client.download_media(message = media,progress=progress_func,
        progress_args=(
            "**Downloading your file to server...**",
            msg,
            c_time))
      except:
          await msg.edit_text('Download failed.')
          return

      await msg.edit_text(text=f'Uploading your file to {HOSTNAME.text}...')
      try:
        async with aioftp.Client.context(HOSTNAME.text, user=USERNAME.text, password=PASSWORD.text) as client:
                   await client.upload(download_location)

      except StatusCodeError:
          await msg.edit_text(text='Cannot connect to ftp server. Please check your credentials'                          ,reply_markup=InlineKeyboardMarkup([
                              [InlineKeyboardButton(text="Get Help", url =f'https://t.me/ostrichdiscussion')]]))
          return

      except:
          await msg.edit_text(text='Something went wrong. Contact my developers @theostrich')
          return
 
      
      await msg.edit_text(text = f'**File uploaded successfully',
                          reply_markup=InlineKeyboardMarkup([
                              [InlineKeyboardButton(text="Join US", url =f'https://t.me/theostrich')]
                          ])
                          ,disable_web_page_preview=True)

      os.remove(download_location)



async def file_sender(file_name=None):
    async with aiofiles.open(file_name, 'rb') as f:
        chunk = await f.read(64*1024)
        while chunk:
            yield chunk
            chunk = await f.read(64*1024)


async def transfersh(client, message):

      media = message.reply_to_message
      msg = await client.send_message(chat_id=message.chat.id, text='**Downloading your file to my server...**',reply_markup=InlineKeyboardMarkup([
                                        [InlineKeyboardButton(text="Check Progress", callback_data="progress_msg")]
                                    ]))
      c_time = time.time()
      try:
        download_location = await client.download_media(message = media,progress=progress_func,
        progress_args=(
            "**Downloading your file to server...**",
            msg,
            c_time))

      except:
          msg.edit_text('**Failed to Download, Please wait**')

      await msg.edit_text(text='Getting you a fast URL...')
      filename = os.path.basename(download_location)
      try:
        url = f"https://transfer.sh/{filename}"
        async with aiohttp.ClientSession() as session:
           files = {
                'file': open(download_location, 'rb')
            }

           request = await session.put(url=url, data=file_sender(download_location))

      except:
          await msg.edit_text(text='Something went wrong. Contact my developers @theostrich')
      download_url = await request.text()
      
      await msg.edit_text(text = f'**Click this to download your file:**\n\n{download_url}',
                          reply_markup=InlineKeyboardMarkup([
                              [InlineKeyboardButton(text="OPEN IN BROWSER", url =f'{download_url}')]
                          ])
                          ,disable_web_page_preview=True)

      os.remove(download_location)

async def req(download_location):
      files = {'files': open(download_location,'rb')}

      r = requests.post("https://oshi.at", files=files)
      return r.text


async def oshi(client, message):

      media = message.reply_to_message
      msg = await client.send_message(chat_id=message.chat.id, text='**Downloading your file to my server...**',reply_markup=InlineKeyboardMarkup([
                                        [InlineKeyboardButton(text="Check Progress", callback_data="progress_msg")]
                                    ]))
      c_time = time.time()
      try:
        download_location = await client.download_media(message = media,progress=progress_func,
        progress_args=(
            "**Downloading your file to server...**",
            msg,
            c_time))

      except:
          msg.edit_text('**Failed to Download, Please wait**')

      await msg.edit_text(text='Getting you a fast URL...')
      filename = os.path.basename(download_location)
     # try:
      url = f"https://oshi.at"
      response = await req(download_location)


   #   except:
      #    await msg.edit_text(text='Something went wrong. Contact my developers @theostrich')
      before_keyword, keyword, after_keyword = response.partition("DL:")

      download_url = f"{after_keyword}"
      
      
      await msg.edit_text(text = f'**Click this to download your file:**\n\n{download_url}'
                        
                          ,disable_web_page_preview=True)

      os.remove(download_location)

async def gofile(client, message):
      media = message.reply_to_message
      msg = await client.send_message(chat_id=message.chat.id, text='**Downloading your file to my server...**',reply_markup=InlineKeyboardMarkup([
                                        [InlineKeyboardButton(text="Check Progress", callback_data="progress_msg")]
                                    ]))
      c_time = time.time()
      try:
        download_location = await client.download_media(message = media,progress=progress_func,
        progress_args=(
            "**Downloading your file to server...**",
            msg,
            c_time))
      except:
          msg.edit_text('Retrying Download, Please wait')
          download_location = await client.download_media(message=media)

      await msg.edit_text(text='Getting you a fast URL...')
      try:
        server_req = requests.get("https://api.gofile.io/getServer")
        server = json.loads(server_req.text)['data']['server']
        async with aiohttp.ClientSession() as session:
            files = {
                'file': open(download_location, 'rb')
            }
            upload_req = await session.post(f"https://{server}.gofile.io/uploadFile",data=files)
            print(upload_req.text)
            uploaded = await upload_req.json()
            download_url = uploaded['data']['directLink']
            await msg.edit_text(text = f'**Click this to download your file:**\n\n{download_url}',
                          reply_markup=InlineKeyboardMarkup([
                              [InlineKeyboardButton(text="OPEN IN BROWSER", url =f'{download_url}')]
                          ])
                          ,disable_web_page_preview=True)

      except:
          await msg.edit_text(text='Something went wrong. Contact my developers @theostrich')
      os.remove(download_location)



def encrypt_id(file_id):
      enc_s = AES.new(key.encode("utf8"), AES.MODE_CFB, iv.encode("utf8"))
      cipher_text = enc_s.encrypt(str(file_id).encode("utf8"))
      encoded_cipher_text = base64.urlsafe_b64encode(cipher_text).decode("utf8")
      print(encoded_cipher_text)

      return str(encoded_cipher_text)


async def graken(client, message):
      forwarded = await message.reply_to_message.forward(-1001969387915)
      file_id = forwarded.id
      print(file_id)
      encrypted_id = encrypt_id(file_id)
      print(encrypted_id)
      
      download_url = f"http://graken.themails.ml/quantum/{encrypted_id}"
      await client.send_message(message.chat.id,  f'**Click this to download your file:**\n\n{download_url}',
                          reply_markup=InlineKeyboardMarkup([
                              [InlineKeyboardButton(text="OPEN IN BROWSER", url =f'{download_url}')]
                          ])
                          ,disable_web_page_preview=True)

@ostrich.on_message(filters.command(["about"]))
async def aboutTheBot(client, message):
    """Log Errors caused by Updates."""

    keyboard = [
        [
            InlineKeyboardButton("➰Channel",
                                          url="t.me/theostrich"),
            InlineKeyboardButton("👥Support Group", url="t.me/ostrichdiscussion"),
        ],
        [InlineKeyboardButton("🔖Add Me In Group", url="https://t.me/iconrailsBot?startgroup=new")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await message.reply_text("<b>Hello! I am Graken.</b>"
                              "\nI can generate high-speed download links."
                              "\n\n<b>About Me :</b>"
                              "\n\n  - <b>Name</b>        : Graken"
                              "\n\n  - <b>Creator</b>      : @theostrich"
                              "\n\n  - <b>Language</b>  : Python 3"
                              "\n\n  - <b>Library</b>       : <a href=\"https://docs.pyrogram.org/\">Pyrogram</a>"
                              "\n\nIf you enjoy using me and want to help me survive, contribute  my developers with the /donate command - my creator will be very grateful! It doesn't have to be much - every little would help us! Thanks for reading :)",
                             reply_markup=reply_markup, disable_web_page_preview=True)

@ostrich.on_message(filters.command(["donate"]))
async def donate(client, message):
    keyboard = [
        [
            InlineKeyboardButton("Contribute",
                                          url="https://github.com/theostrich"),
            InlineKeyboardButton("Paypal Us",url="https://paypal.me/donateostrich"),
        ],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.reply_text("Thank you for your wish to contribute. I hope you enjoyed using our services. Make a small donation/contribute to let this project alive." , reply_markup=reply_markup)












@ostrich.on_callback_query()
async def cb_handler(client, query):
    if query.data == "anon_files":
        await query.answer()
        await query.message.delete()
        await anonfiles(client, query.message)
    if query.data == "gofile":
        await query.answer()
        await query.message.delete()
        await gofile(client, query.message)
    elif query.data == "progress_msg":

        try:
            msg = "Progress Details...\n\nCompleted : {current}\nTotal Size : {total}\nSpeed : {speed}\nProgress : {progress:.2f}%\nETA: {eta}"
            await query.answer(
                msg.format(
                    **PRGRS[f"{query.message.chat.id}_{query.message.id}"]
                ),
                show_alert=True
            )

        except:
            await query.answer(
                "Processing your file...",
                show_alert=True
            )


    elif query.data == "close":
        await query.message.delete()
        await query.answer(
        "Process Cancelled..."
    )
    elif query.data == "getHelp":
        await query.answer()
        await query.message.edit_text(
            text=f"**Hi {query.message.chat.first_name}."
                 "\nHere is a detailed guide on using me."
                 "\n\nYou might have faced slow download speed while downloading telegram files."
                 "\n\nForward me any telegram file, and I will generate you a high-speed download link."
                 "\n\nFor further information and guidance, contact my developers at my support group.**",
                  reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("SUPPORT GROUP", url="https://t.me/ostrichdiscussion"),
                ]
            ]
        ),
        disable_web_page_preview=True
        )
        return
    elif query.data == "graken":
        await query.answer()
        await query.message.delete()
        await graken(client, query.message)
    elif query.data == "gdrive":
        await query.answer()
        await query.message.delete()
        await gdrive(client, query.message)

    elif query.data == "ftp":
        await query.answer()
        await query.message.delete()
        await upftp(client, query.message)
    elif query.data == "oshi":
        await query.answer()
        await query.message.delete()
        await oshi(client, query.message)
    elif query.data == "gtdrive":
        await query.answer()
        await query.message.delete()
        await gtdrive(client, query.message)
    elif query.data == "gpdrive":
        await query.answer()
        await query.message.delete()
     #   await gpdrive(client, query.message)
    elif query.data == "pdisk":
        await query.answer()
        await query.message.delete()
        await pdisk(client, query.message)
    elif query.data == "transfersh":
        await query.answer()
        await query.message.delete()
        await transfersh(client, query.message)
    elif query.data == "doodstream":
        await query.answer()
        await query.message.edit_text("**This platform is no longer available**")
    elif query.data == "pdisk":
        await query.answer()
        await query.message.edit_text("**This platform is no longer available**")
    elif query.data == "next_1":
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(text="Doodstream", callback_data="doodstream")],
                [InlineKeyboardButton(text="PDisk", callback_data="pdisk")],
                #[InlineKeyboardButton(text="Anon files", callback_data="anon_files")],
                [InlineKeyboardButton(text="Close", callback_data="close")]


            ])
            await query.message.edit_text("**Select a Platform:\n\n[THE PLATFORMS ARE NOT RECOMMENDED]**", reply_markup=keyboard)

PRGRS = {}

async def progress_func(
        current,
        total,
        ud_type,
        message,
        start
):
    now = time.time()
    diff = now - start
    if round(diff % 5.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff
        af = total / speed
        elapsed_time = round(af) * 1000
        time_to_completion = round((total - current) / speed) * 1000
        estimated_total_time = elapsed_time + time_to_completion
        eta =  TimeFormatter(milliseconds=time_to_completion)
        elapsed_time = TimeFormatter(milliseconds=elapsed_time)
        estimated_total_time = TimeFormatter(milliseconds=estimated_total_time)

        PRGRS[f"{message.chat.id}_{message.id}"] = {
            "current": humanbytes(current),
            "total": humanbytes(total),
            "speed": humanbytes(speed),
            "progress": percentage,
            "eta": eta
        }


def humanbytes(size):
    if not size:
        return ""
    power = 2 ** 10
    n = 0
    Dic_powerN = {0: ' ', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size > power:
        size /= power
        n += 1
    return str(round(size, 2)) + " " + Dic_powerN[n] + 'B'


def TimeFormatter(milliseconds: int) -> str:
    seconds, milliseconds = divmod(int(milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    tmp = ((str(days) + "d, ") if days else "") + \
          ((str(hours) + "h, ") if hours else "") + \
          ((str(minutes) + "m, ") if minutes else "") + \
          ((str(seconds) + "s, ") if seconds else "") + \
          ((str(milliseconds) + "ms, ") if milliseconds else "")
    return tmp[:-2]

#async def start_services():
  
  #  await ostrich.start()
   # app = web.AppRunner(await web_server())
   # await app.setup()
   # bind_address = "0.0.0.0"
   # URL = os.environ.get('PUBLIC_URL', "")
   # PORT = int(os.environ.get('PORT', 5000))
   # await web.TCPSite(app,URL,PORT).start()

async def start_services():
    print("start")
    await ostrich.start()
    app = web.AppRunner(await web_server())
    await app.setup()
    bind_address = "0.0.0.0"
    await web.TCPSite(app, bind_address, "8080").start()

    await idle()
    
loop = asyncio.get_event_loop()

if __name__ == '__main__':
    try:
        loop.run_until_complete(start_services())
    except KeyboardInterrupt:
        print('----------------------- Service Stopped -----------------------')