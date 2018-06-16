import asyncio
import datetime
import os
import re
import sys
from enum import Enum, unique
from struct import unpack
from string import Template

from google.cloud import speech, texttospeech
from google.cloud.speech import enums
from google.cloud.speech import types

import numpy as np

import prettytable
import pyaudio

RATE = 44100


@unique
class DeviceType(Enum):
    Unknown = 0
    Temperature = 1
    Humidity = 2


class IoTDevice:
    @classmethod
    def get_unique(cls, addr, devicetype):
        return "{}:{}".format(addr, devicetype)

    def __init__(self, chipid, devicetype, addr):
        self.type = devicetype
        self.id = chipid
        self.updatetime = datetime.datetime.now()
        self.value = 0.
        self.addr = addr
        self.unique = IoTDevice.get_unique(addr, devicetype)

    def update(self, value):
        self.value = value
        self.updatetime = datetime.datetime.now()


class IoTServerProtocol:
    def __init__(self):
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr):
        head = data[0]
        if head == 0:
            _, dtype, cid = unpack('<BBI', data)
            d = IoTDevice(cid, dtype, addr)
            devices[d.unique] = d
        else:
            d, value = unpack('<Bf', data)
            uid = IoTDevice.get_unique(addr, d)
            if uid in devices:
                devices[IoTDevice.get_unique(addr, d)].update(value)
            else:
                self.transport.sendto(b'\x00', addr)
                return

        print('Received %d from %s' % (head, addr))
        self.transport.sendto(b'\xff', addr)


async def print_loop():
    while True:
        table = prettytable.PrettyTable(['Chip Id', 'Device Type', 'Value', 'Update Time', 'Address'])
        for _, v in devices.items():
            table.add_row([v.id, DeviceType(v.type).name, v.value, v.updatetime, v.addr])
        print(table)
        await asyncio.sleep(3)


class NicoAssistant:
    patterns = [
        {"input": [], "output": ['Sorry, can you say again?', 'Could you try speaking loudly, please.']},
        {"input": ['hi', 'hello'], "output": ['Hi, what can i do for you', 'Hello']},
        {"input": ['name', 'your'], "output": ['My name is $Name', 'I am $Name']},
        {"input": ['temperature', 'what', 'what\'s'],
         "output": ['The temperature is $Temperature centigrade'],
         "error": ['Sorry, temperature information is not available now']},
        {"input": ['humidity', 'what', 'what\'s'], "output": ['The humidity is $Humidity%'],
         "error": ['Sorry, humidity information is not available now']},
    ]

    def getkws(self):
        kws = {'Name': self.name}
        for d in devices.values():
            kws[DeviceType(d.type).name] = d.value
        return kws

    def say(self, pattern):
        s = np.random.choice(pattern['output'])

        try:
            s = Template(s).substitute(self.getkws())
        except KeyError:
            s = np.random.choice(pattern['error'])

        response = self.tts_client.synthesize_speech(
            texttospeech.types.SynthesisInput(text=s), self.voice,
            self.audio_config)
        self.play_stream.start_stream()
        self.play_stream.write(response.audio_content)
        self.play_stream.stop_stream()
        print("said '{}'".format(s))

    async def react_once(self):
        response = await self.record_audio()
        print(response)

        if len(response.results) == 0:
            print("no detection")
            self.loop.run_in_executor(None, self.say, self.patterns[0])
            return

        scores = np.zeros(len(self.patterns))
        words = list(map(str.lower, re.findall('\\b\\w+\\b', response.results[0].alternatives[0].transcript)))
        for i, p in enumerate(self.patterns):
            cross = [w for w in p['input'] if w in words]
            scores[i] = len(cross)

        self.loop.run_in_executor(None, self.say, self.patterns[np.argmax(scores)])

    async def record_audio(self):
        total_size = RATE * 5
        content = bytearray()

        print("start recording")
        self.record_stream.start_stream()
        while len(content) < total_size:
            content.extend(await self.audio_queue.get())
        print("stop recording")
        self.record_stream.stop_stream()

        return await self.loop.run_in_executor(None, self.speech_client.recognize, self.speech_config,
                                               types.RecognitionAudio(content=bytes(content)))

    def record_callback(self, in_data, frame_count, time_info, status):
        asyncio.run_coroutine_threadsafe(self.audio_queue.put(in_data), self.loop)
        return None, pyaudio.paContinue

    def __init__(self, loop, credential='google.json', rate=RATE, language_code='en-US', name='Zhaoyuan'):
        self.name = name
        self.rate = rate
        self.credential = credential
        self.loop = loop

        self.keywords = []
        for p in self.patterns:
            self.keywords.extend(p["input"])
        print("keywords are {}".format(self.keywords))

        self.audio_queue = asyncio.Queue(maxsize=10)

        audio = pyaudio.PyAudio()
        self.record_stream = audio.open(format=pyaudio.paInt16,
                                        channels=1,
                                        rate=rate,
                                        input=True,
                                        start=False,
                                        stream_callback=self.record_callback)
        self.play_stream = audio.open(format=pyaudio.paInt16,
                                      channels=1,
                                      rate=rate,
                                      start=False,
                                      output=True)

        os.environ.setdefault('GOOGLE_APPLICATION_CREDENTIALS', credential)
        self.speech_client = speech.SpeechClient()
        self.speech_config = types.RecognitionConfig(
            encoding=enums.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=rate,
            language_code=language_code,
            speech_contexts=[types.SpeechContext(
                phrases=self.keywords,
            )]
        )

        self.tts_client = texttospeech.TextToSpeechClient()
        self.voice = texttospeech.types.VoiceSelectionParams(
            language_code='en-US',
            ssml_gender=texttospeech.enums.SsmlVoiceGender.FEMALE
        )
        self.audio_config = texttospeech.types.AudioConfig(
            audio_encoding=texttospeech.enums.AudioEncoding.LINEAR16,
            sample_rate_hertz=rate
        )

        print('assistant ok')


async def aio_readline(loop):
    while True:
        await loop.run_in_executor(None, sys.stdin.readline)
        asyncio.ensure_future(assistant.react_once())


devices = {}

loop = asyncio.get_event_loop()
print("Starting UDP server")
# One protocol instance will be created to serve all client requests
listen = loop.create_datagram_endpoint(
    IoTServerProtocol, local_addr=("0.0.0.0", 20180))
transport, protocol = loop.run_until_complete(listen)

assistant = NicoAssistant(loop)

asyncio.ensure_future(print_loop())
asyncio.ensure_future(aio_readline(loop))

try:
    loop.run_forever()
except KeyboardInterrupt:
    pass

transport.close()
loop.close()
