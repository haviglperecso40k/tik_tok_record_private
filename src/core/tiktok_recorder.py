import os
import random
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.client import HTTPException
from multiprocessing import Process
from threading import Thread

from requests import RequestException

from core.tiktok_api import TikTokAPI
from utils.logger_manager import logger
from utils.video_management import VideoManagement
from upload.telegram import Telegram
from utils.custom_exceptions import LiveNotFound, UserLiveError, \
    TikTokRecorderError, IPBlockedByWAF
from utils.enums import Mode, Error, TimeOut, TikTokError


def _record_worker(user, room_id, proxy, cookies, output, duration, use_telegram):
    """
    Standalone picklable function để chạy trong subprocess trên Windows.
    """
    recorder = TikTokRecorder(
        url=None, user=user, room_id=room_id,
        mode=Mode.MANUAL,
        automatic_interval=5,
        cookies=cookies, proxy=proxy,
        output=output, duration=duration,
        use_telegram=use_telegram,
    )
    recorder.start_recording(user, room_id)


class TikTokRecorder:

    def __init__(
        self,
        url,
        user,
        room_id,
        mode,
        automatic_interval,
        cookies,
        proxy,
        output,
        duration,
        use_telegram,
        watchlist_file=None,
        shard_index=0,
        shard_count=1,
        max_workers=3,
        jitter_seconds=30,
        backoff_minutes=15,
    ):
        # Setup TikTok API client
        self.tiktok = TikTokAPI(proxy=proxy, cookies=cookies)
        self.cookies = cookies

        # TikTok Data
        self.url = url
        self.user = user
        self.room_id = room_id

        # Tool Settings
        self.mode = mode
        self.automatic_interval = automatic_interval
        self.duration = duration
        self.output = output
        self.proxy = proxy
        self.watchlist_file = watchlist_file
        self.shard_index = shard_index
        self.shard_count = shard_count
        self.max_workers = max_workers
        self.jitter_seconds = jitter_seconds
        self.backoff_minutes = backoff_minutes

        # Upload Settings
        self.use_telegram = use_telegram

        # Check if the user's country is blacklisted
        self.check_country_blacklisted()

        # Retrieve sec_uid if the mode is FOLLOWERS
        if self.mode == Mode.WATCHLIST:
            logger.info("Watchlist mode activated\n")

        elif self.mode == Mode.FOLLOWERS:
            self.sec_uid = self.tiktok.get_sec_uid()
            if self.sec_uid is None:
                raise TikTokRecorderError("Failed to retrieve sec_uid.")

            logger.info(f"Followers mode activated\n")
        else:
            # Get live information based on the provided user data
            if self.url:
                self.user, self.room_id = \
                    self.tiktok.get_room_and_user_from_url(self.url)

            if not self.user:
                self.user = self.tiktok.get_user_from_room_id(self.room_id)

            if not self.room_id:
                self.room_id = self.tiktok.get_room_id_from_user(self.user)

            logger.info(
                f"USERNAME: {self.user}" + ("\n" if not self.room_id else ""))
            logger.info(f"ROOM_ID:  {self.room_id}" + (
                "\n" if not self.tiktok.is_room_alive(self.room_id) else ""))

        # If proxy is provided, set up the HTTP client without the proxy
        if proxy:
            self.tiktok = TikTokAPI(proxy=None, cookies=cookies)

    def run(self):
        """
        runs the program in the selected mode. 
        
        If the mode is MANUAL, it checks if the user is currently live and
        if so, starts recording.
        
        If the mode is AUTOMATIC, it continuously checks if the user is live
        and if not, waits for the specified timeout before rechecking.
        If the user is live, it starts recording.
        """

        if self.mode == Mode.MANUAL:
            self.manual_mode()

        elif self.mode == Mode.AUTOMATIC:
            self.automatic_mode()

        elif self.mode == Mode.FOLLOWERS:
            self.followers_mode()

        elif self.mode == Mode.WATCHLIST:
            self.watchlist_mode_sharded()

    def manual_mode(self):
        if not self.tiktok.is_room_alive(self.room_id):
            raise UserLiveError(
                f"@{self.user}: {TikTokError.USER_NOT_CURRENTLY_LIVE}"
            )

        self.start_recording(self.user, self.room_id)

    def automatic_mode(self):
        while True:
            try:
                self.room_id = self.tiktok.get_room_id_from_user(self.user)
                self.manual_mode()

            except UserLiveError as ex:
                logger.info(ex)
                logger.info(f"Waiting {self.automatic_interval} minutes before recheck\n")
                time.sleep(self.automatic_interval * TimeOut.ONE_MINUTE)

            except LiveNotFound as ex:
                logger.error(f"Live not found: {ex}")
                logger.info(f"Waiting {self.automatic_interval} minutes before recheck\n")
                time.sleep(self.automatic_interval * TimeOut.ONE_MINUTE)

            except ConnectionError:
                logger.error(Error.CONNECTION_CLOSED_AUTOMATIC)
                time.sleep(TimeOut.CONNECTION_CLOSED * TimeOut.ONE_MINUTE)

            except Exception as ex:
                logger.error(f"Unexpected error: {ex}\n")

    def followers_mode(self):
        active_recordings = {}  # follower -> Process

        while True:
            try:
                followers = self.tiktok.get_followers_list(self.sec_uid)

                for follower in followers:
                    if follower in active_recordings:
                        if not active_recordings[follower].is_alive():
                            logger.info(f'Recording of @{follower} finished.')
                            del active_recordings[follower]
                        else:
                            continue

                    try:
                        room_id = self.tiktok.get_room_id_from_user(follower)

                        if not room_id or not self.tiktok.is_room_alive(room_id):
                            #logger.info(f"@{follower} is not live. Skipping...")
                            continue

                        logger.info(f"@{follower} is live. Starting recording...")

                        process = Thread(
                            target=self.start_recording,
                            args=(follower, room_id),
                            daemon=True
                        )
                        process.start()
                        active_recordings[follower] = process

                        time.sleep(2.5)

                    except Exception as e:
                        logger.error(f'Error while processing @{follower}: {e}')
                        continue

                print()
                delay = self.automatic_interval * TimeOut.ONE_MINUTE
                logger.info(f'Waiting {delay} minutes for the next check...')
                time.sleep(delay)

            except UserLiveError as ex:
                logger.info(ex)
                logger.info(f"Waiting {self.automatic_interval} minutes before recheck\n")
                time.sleep(self.automatic_interval * TimeOut.ONE_MINUTE)

            except ConnectionError:
                logger.error(Error.CONNECTION_CLOSED_AUTOMATIC)
                time.sleep(TimeOut.CONNECTION_CLOSED * TimeOut.ONE_MINUTE)

            except Exception as ex:
                logger.error(f"Unexpected error: {ex}\n")
                time.sleep(self.automatic_interval * TimeOut.ONE_MINUTE)

    def get_watchlist_path(self):
        if self.watchlist_file:
            return os.path.abspath(self.watchlist_file)

        watchlist_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..',
            'watchlist.txt'
        )
        return os.path.normpath(watchlist_path)

    def load_watchlist_users(self, watchlist_path):
        users = []
        seen = set()

        with open(watchlist_path, 'r', encoding='utf-8') as f:
            for line in f:
                username = line.strip()
                if not username or username.startswith('#'):
                    continue

                username = username.lstrip('@').strip()
                username_key = username.lower()
                if username and username_key not in seen:
                    users.append(username)
                    seen.add(username_key)

        return users

    def user_belongs_to_shard(self, user):
        if self.shard_count <= 1:
            return True

        shard = zlib.crc32(user.lower().encode('utf-8')) % self.shard_count
        return shard == self.shard_index

    def sleep_startup_jitter(self):
        if self.jitter_seconds <= 0:
            return

        delay = random.uniform(0, self.jitter_seconds)
        if delay < 1:
            return

        logger.info(f"Startup jitter: waiting {delay:.1f} seconds before first check.")
        time.sleep(delay)

    def sleep_request_jitter(self):
        if self.jitter_seconds <= 0:
            return

        time.sleep(random.uniform(0, min(2.0, self.jitter_seconds)))

    def sleep_poll_interval(self):
        base_delay = self.automatic_interval * TimeOut.ONE_MINUTE
        jitter = min(self.jitter_seconds, base_delay * 0.25)
        delay = base_delay

        if jitter > 0:
            delay += random.uniform(-jitter, jitter)

        delay = max(1, delay)
        logger.info(f'Waiting {delay / TimeOut.ONE_MINUTE:.1f} minutes for the next check...\n')
        time.sleep(delay)

    def sleep_backoff(self, reason):
        base_delay = self.backoff_minutes * TimeOut.ONE_MINUTE
        jitter = min(self.jitter_seconds, base_delay * 0.25)
        delay = base_delay + (random.uniform(0, jitter) if jitter > 0 else 0)

        logger.error(
            f"Rate-limit/WAF signal detected ({reason}). "
            f"Backing off for {delay / TimeOut.ONE_MINUTE:.1f} minutes."
        )
        time.sleep(delay)

    def watchlist_mode_sharded(self):
        watchlist_path = self.get_watchlist_path()

        if not os.path.exists(watchlist_path):
            raise TikTokRecorderError(TikTokError.WATCHLIST_FILE_NOT_FOUND)

        active_recordings = {}  # username -> Thread
        self.sleep_startup_jitter()

        while True:
            try:
                all_users = self.load_watchlist_users(watchlist_path)
                if not all_users:
                    raise TikTokRecorderError(TikTokError.WATCHLIST_EMPTY)

                users = [u for u in all_users if self.user_belongs_to_shard(u)]
                if not users:
                    logger.info(
                        f"Shard {self.shard_index}/{self.shard_count}: "
                        f"no users assigned from {len(all_users)} total users."
                    )
                    self.sleep_poll_interval()
                    continue

                for u in list(active_recordings):
                    if not active_recordings[u].is_alive():
                        logger.info(f'Recording of @{u} finished.')
                        del active_recordings[u]

                users_to_check = [u for u in users if u not in active_recordings]
                logger.info(
                    f"Shard {self.shard_index}/{self.shard_count}: "
                    f"checking {len(users_to_check)}/{len(users)} assigned users "
                    f"from {len(all_users)} total (max_workers={self.max_workers})."
                )

                thread_state = threading.local()

                def get_worker_api():
                    if not hasattr(thread_state, 'tiktok'):
                        thread_state.tiktok = TikTokAPI(
                            proxy=self.proxy,
                            cookies=self.cookies
                        )
                    return thread_state.tiktok

                def check_user(user):
                    try:
                        self.sleep_request_jitter()
                        tiktok = get_worker_api()
                        room_id = tiktok.get_room_id_from_user(user)
                        if room_id and tiktok.is_room_alive(room_id):
                            return user, room_id, None
                    except UserLiveError:
                        return user, None, None
                    except IPBlockedByWAF:
                        return user, None, 'ip blocked by WAF'
                    except RequestException as ex:
                        status = getattr(getattr(ex, 'response', None), 'status_code', None)
                        if status in (403, 429):
                            return user, None, f'HTTP {status}'
                        return user, None, None
                    except Exception as ex:
                        message = str(ex).lower()
                        if any(token in message for token in ('403', '429', 'waf', 'captcha', 'blocked', 'too many')):
                            return user, None, str(ex) or 'rate-limit signal'
                    return user, None, None

                backoff_reason = None
                if users_to_check:
                    max_workers = min(self.max_workers, len(users_to_check))
                    executor = ThreadPoolExecutor(max_workers=max_workers)
                    futures = {executor.submit(check_user, u): u for u in users_to_check}
                    try:
                        for future in as_completed(futures):
                            user, room_id, reason = future.result()
                            if reason:
                                backoff_reason = reason
                                break

                            if not room_id or user in active_recordings:
                                continue

                            logger.info(f"@{user} is live. Starting recording...")
                            t = Thread(
                                target=self.start_recording,
                                args=(user, room_id),
                                daemon=True
                            )
                            t.start()
                            active_recordings[user] = t
                    finally:
                        executor.shutdown(
                            wait=backoff_reason is None,
                            cancel_futures=backoff_reason is not None
                        )

                print()
                if backoff_reason:
                    self.sleep_backoff(backoff_reason)
                else:
                    self.sleep_poll_interval()

            except TikTokRecorderError:
                raise

            except ConnectionError:
                logger.error(Error.CONNECTION_CLOSED_AUTOMATIC)
                self.sleep_backoff('connection closed')

            except Exception as ex:
                logger.error(f"Unexpected error: {ex}\n")
                self.sleep_poll_interval()

    def start_recording(self, user, room_id):
        """
        Start recording live
        """
        recording_tiktok = TikTokAPI(proxy=None, cookies=self.cookies)
        live_url = recording_tiktok.get_live_url(room_id)
        if not live_url:
            raise LiveNotFound(TikTokError.RETRIEVE_LIVE_URL)

        current_date = time.strftime("%Y.%m.%d_%H-%M-%S", time.localtime())
        day_folder = time.strftime("%d_%m", time.localtime())

        base_output = self.output if (isinstance(self.output, str) and self.output != '') else ''
        if base_output and not (base_output.endswith('/') or base_output.endswith('\\')):
            base_output = base_output + ("\\" if os.name == 'nt' else "/")

        output_dir = os.path.join(base_output, day_folder) if base_output else day_folder
        os.makedirs(output_dir, exist_ok=True)

        output = os.path.join(output_dir, f"TK_{user}_{current_date}_flv.mp4")

        if self.duration:
            logger.info(f"Started recording for {self.duration} seconds ")
        else:
            logger.info("Started recording...")

        buffer_size = 512 * 1024 # 512 KB buffer
        buffer = bytearray()

        logger.info("[PRESS CTRL + C ONCE TO STOP]")
        with open(output, "wb") as out_file:
            stop_recording = False
            while not stop_recording:
                try:
                    if not recording_tiktok.is_room_alive(room_id):
                        logger.info("User is no longer live. Stopping recording.")
                        break

                    start_time = time.time()
                    for chunk in recording_tiktok.download_live_stream(live_url):
                        buffer.extend(chunk)
                        if len(buffer) >= buffer_size:
                            out_file.write(buffer)
                            buffer.clear()

                        elapsed_time = time.time() - start_time
                        if self.duration and elapsed_time >= self.duration:
                            stop_recording = True
                            break

                except ConnectionError:
                    if self.mode == Mode.AUTOMATIC:
                        logger.error(Error.CONNECTION_CLOSED_AUTOMATIC)
                        time.sleep(TimeOut.CONNECTION_CLOSED * TimeOut.ONE_MINUTE)

                except (RequestException,HTTPException):
                    time.sleep(2)

                except KeyboardInterrupt:
                    logger.info("Recording stopped by user.")
                    stop_recording = True

                except Exception as ex:
                    logger.error(f"Unexpected error: {ex}\n")
                    stop_recording = True

                finally:
                    if buffer:
                        out_file.write(buffer)
                        buffer.clear()
                    out_file.flush()

        logger.info(f"Recording finished: {output}\n")
        VideoManagement.convert_flv_to_mp4(output)

        if self.use_telegram:
            Telegram().upload(output.replace('_flv.mp4', '.mp4'))

    def check_country_blacklisted(self):
        is_blacklisted = self.tiktok.is_country_blacklisted()
        if not is_blacklisted:
            return False

        if self.room_id is None:
            raise TikTokRecorderError(TikTokError.COUNTRY_BLACKLISTED)

        if self.mode == Mode.AUTOMATIC:
            raise TikTokRecorderError(TikTokError.COUNTRY_BLACKLISTED_AUTO_MODE)

        elif self.mode == Mode.FOLLOWERS:
            raise TikTokRecorderError(TikTokError.COUNTRY_BLACKLISTED_FOLLOWERS_MODE)

        elif self.mode == Mode.WATCHLIST:
            raise TikTokRecorderError(TikTokError.COUNTRY_BLACKLISTED_WATCHLIST_MODE)

        return is_blacklisted
