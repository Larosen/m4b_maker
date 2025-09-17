#!/usr/bin/env python3
"""
Modern Audiobook Converter with FFmpeg 7.1.2
Converts MP3 audiobooks to M4B with proper metadata using beets-audible
Workflow: Input (Author/Book/*.mp3) -> Beets Tagging -> FFmpeg M4B -> Output (Author/Book/Book.m4b)
"""

import os
import sys
import time
import json
import logging
import subprocess
import re
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import yaml
import shutil
from mutagen import File
from mutagen.id3 import ID3, TALB, TIT2, TPE1, TDRC

class AudiobookConverter:
    def __init__(self, config_path="/config/converter.yaml"):
        self.config = self.load_config(config_path)
        self.setup_logging()
        self.input_dir = Path(self.config['directories']['input'])
        self.output_dir = Path(self.config['directories']['output'])
        self.temp_dir = Path(self.config['directories']['temp'])
        self.processing_queue = []
        
        # Ensure directories exist
        for directory in [self.input_dir, self.output_dir, self.temp_dir]:
            directory.mkdir(parents=True, exist_ok=True)
        
    def load_config(self, config_path):
        """Load configuration from YAML file with defaults"""
        default_config = {
            'directories': {
                'input': '/input',
                'output': '/output',
                'temp': '/temp'
            },
            'conversion': {
                'audio_bitrate': '64k',
                'audio_codec': 'libfdk_aac',
                'max_chapter_length': 900,  # 15 minutes
                'jobs': 4,
                'quality_profile': 'high'  # high, medium, low
            },
            'beets': {
                'enable_audible': True,
                'auto_tag': True,
                'tag_before_conversion': True,  # Tag individual tracks before M4B merge
                'fetch_art': True
            },
            'output_structure': {
                'pattern': 'author/book/file',  # author/book/file.m4b
                'sanitize_names': True,
                'max_filename_length': 200
            },
            'logging': {
                'level': 'INFO',
                'file': '/logs/converter.log'
            }
        }
        
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
                # Merge with defaults recursively
                for key, value in default_config.items():
                    if key not in config:
                        config[key] = value
                    elif isinstance(value, dict):
                        for subkey, subvalue in value.items():
                            if subkey not in config[key]:
                                config[key][subkey] = subvalue
                return config
        except FileNotFoundError:
            # Create default config
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, 'w') as f:
                yaml.dump(default_config, f, default_flow_style=False)
            return default_config
    
    def setup_logging(self):
        """Setup logging configuration"""
        log_level = getattr(logging, self.config['logging']['level'].upper())
        log_dir = Path(self.config['logging']['file']).parent
        log_dir.mkdir(parents=True, exist_ok=True)
        
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.config['logging']['file']),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)
        self.logger.info("Audiobook Converter started with FFmpeg 7.1.2")
    
    def sanitize_filename(self, filename):
        """Sanitize filename for filesystem compatibility"""
        if not self.config['output_structure']['sanitize_names']:
            return filename
            
        # Remove/replace problematic characters
        filename = re.sub(r'[<>:"/\\|?*]', '', filename)
        filename = re.sub(r'\s+', ' ', filename).strip()
        
        # Limit length
        max_length = self.config['output_structure']['max_filename_length']
        if len(filename) > max_length:
            filename = filename[:max_length].rstrip()
            
        return filename
    
    def detect_input_structure(self, input_path):
        """
        Detect if input is already in Author/Book structure or flat structure
        Returns: ('structured', author, book) or ('flat', None, book_name)
        """
        input_path = Path(input_path)
        
        # Check if input path looks like Author/Book/files structure
        if input_path.parent != self.input_dir:
            # This is a nested structure: input_dir/Author/Book
            author = input_path.parent.name
            book = input_path.name
            return ('structured', author, book)
        else:
            # This is flat structure: input_dir/Book
            book = input_path.name
            return ('flat', None, book)
    
    def extract_metadata_from_files(self, book_path):
        """Extract metadata from MP3 files in the directory"""
        audio_files = sorted(list(book_path.glob("*.mp3")) + list(book_path.glob("*.m4a")))
        
        if not audio_files:
            return None
            
        # Try to get metadata from first file
        try:
            audio_file = File(str(audio_files[0]))
            if audio_file is None:
                return None
                
            # Extract metadata from tags
            title = None
            artist = None
            album = None
            year = None
            
            if hasattr(audio_file, 'tags') and audio_file.tags:
                # Try different tag formats
                if hasattr(audio_file.tags, 'get'):
                    # ID3v2 format
                    title = str(audio_file.tags.get('TIT2', [''])[0]) or str(audio_file.tags.get('TALB', [''])[0])
                    artist = str(audio_file.tags.get('TPE1', [''])[0])
                    album = str(audio_file.tags.get('TALB', [''])[0])
                    year_tag = audio_file.tags.get('TDRC', [''])
                    year = str(year_tag[0]) if year_tag else None
                else:
                    # Alternative tag access
                    title = str(audio_file.tags.get('title', [''])[0] or audio_file.tags.get('album', [''])[0])
                    artist = str(audio_file.tags.get('artist', [''])[0])
                    album = str(audio_file.tags.get('album', [''])[0])
                    year = str(audio_file.tags.get('date', [''])[0])
            
            # Clean empty strings
            title = title.strip() if title else None
            artist = artist.strip() if artist else None
            album = album.strip() if album else None
            year = year.strip() if year else None
            
            # Fallback to folder structure
            structure_info = self.detect_input_structure(book_path)
            if structure_info[0] == 'structured':
                # Use folder structure as fallback
                if not artist:
                    artist = structure_info[1]
                if not title and not album:
                    title = structure_info[2]
                    album = structure_info[2]
            else:
                # Flat structure fallback
                if not title and not album:
                    title = book_path.name
                    album = book_path.name
                    
            # Final fallback
            if not artist:
                artist = "Unknown Author"
            if not title:
                title = book_path.name
            if not album:
                album = title
                
            return {
                'title': title,
                'artist': artist,
                'album': album,
                'year': year
            }
            
        except Exception as e:
            self.logger.warning(f"Could not extract metadata from {audio_files[0]}: {e}")
            
            # Fallback to folder structure
            structure_info = self.detect_input_structure(book_path)
            if structure_info[0] == 'structured':
                return {
                    'title': structure_info[2],
                    'artist': structure_info[1],
                    'album': structure_info[2],
                    'year': None
                }
            else:
                return {
                    'title': book_path.name,
                    'artist': "Unknown Author",
                    'album': book_path.name,
                    'year': None
                }
    
    def create_output_structure(self, metadata, book_title):
        """Create the Author/Book/ directory structure in output"""
        author = self.sanitize_filename(metadata['artist'])
        book = self.sanitize_filename(metadata.get('album', book_title))
        
        author_dir = self.output_dir / author
        book_dir = author_dir / book
        
        book_dir.mkdir(parents=True, exist_ok=True)
        
        return book_dir, f"{book}.m4b"
    
    def scan_for_books(self):
        """Scan input directory for new audiobooks (supports both flat and Author/Book structure)"""
        self.logger.info("Scanning for audiobooks...")
        
        # Scan for flat structure (input_dir/Book/)
        for item in self.input_dir.iterdir():
            if item.is_dir():
                audio_files = list(item.glob("*.mp3")) + list(item.glob("*.m4a"))
                if audio_files:
                    self.logger.info(f"Found audiobook: {item.name}")
                    self.process_audiobook(item)
        
        # Scan for nested structure (input_dir/Author/Book/)
        for author_dir in self.input_dir.iterdir():
            if author_dir.is_dir():
                for book_dir in author_dir.iterdir():
                    if book_dir.is_dir():
                        audio_files = list(book_dir.glob("*.mp3")) + list(book_dir.glob("*.m4a"))
                        if audio_files:
                            self.logger.info(f"Found structured audiobook: {author_dir.name}/{book_dir.name}")
                            self.process_audiobook(book_dir)
    
    def process_audiobook(self, book_path):
        """
        Process a single audiobook directory
        Workflow: Extract metadata -> Beets tagging -> FFmpeg M4B conversion -> Move to output
        """
        self.logger.info(f"Processing audiobook: {book_path}")
        
        try:
            # Step 1: Extract initial metadata
            metadata = self.extract_metadata_from_files(book_path)
            if not metadata:
                self.logger.error(f"Could not extract metadata from {book_path}")
                return
            
            self.logger.info(f"Initial metadata - Artist: {metadata['artist']}, Title: {metadata['title']}")
            
            # Step 2: Create output directory structure
            output_book_dir, m4b_filename = self.create_output_structure(metadata, book_path.name)
            final_m4b_path = output_book_dir / m4b_filename
            
            # Skip if already exists
            if final_m4b_path.exists():
                self.logger.info(f"M4B already exists, skipping: {final_m4b_path}")
                shutil.rmtree(book_path)  # Clean up input
                return
            
            # Step 3: Copy to temp directory for processing
            temp_book_path = self.temp_dir / f"processing_{book_path.name}"
            if temp_book_path.exists():
                shutil.rmtree(temp_book_path)
            
            shutil.copytree(book_path, temp_book_path)
            
            # Step 4: Use beets for metadata tagging BEFORE M4B conversion
            enhanced_metadata = metadata
            if self.config['beets']['enable_audible'] and self.config['beets']['tag_before_conversion']:
                enhanced_metadata = self.tag_with_beets(temp_book_path, metadata)
            
            # Step 5: Convert to M4B using FFmpeg 7.1.2
            temp_m4b_file = self.convert_to_m4b_ffmpeg712(temp_book_path, enhanced_metadata, m4b_filename)
            
            # Step 6: Move to final destination
            if temp_m4b_file and temp_m4b_file.exists():
                shutil.move(temp_m4b_file, final_m4b_path)
                self.logger.info(f"Conversion complete: {final_m4b_path}")
                
                # Clean up
                shutil.rmtree(book_path)  # Remove original
                shutil.rmtree(temp_book_path)  # Remove temp
                
                # Log final structure
                self.logger.info(f"Created: {enhanced_metadata['artist']}/{enhanced_metadata.get('album', enhanced_metadata['title'])}/{m4b_filename}")
            else:
                self.logger.error(f"Conversion failed for {book_path}")
            
        except Exception as e:
            self.logger.error(f"Error processing {book_path}: {str(e)}")
    
    def tag_with_beets(self, book_path, initial_metadata):
        """
        Use beets to tag individual audio files with Audible metadata BEFORE M4B conversion
        This allows beets to properly identify albums with multiple tracks
        """
        self.logger.info(f"Tagging individual tracks with beets: {book_path.name}")
        
        # Create temporary beets config
        beets_config = {
            'directory': str(book_path.parent),
            'library': str(self.temp_dir / f'beets_{book_path.name}.db'),
            'plugins': ['audible'],
            'audible': {
                'source_weight': 0.8,
                'fetch_art': True,
                'timeout': 30
            },
            'import': {
                'autotag': True,
                'copy': False,
                'move': False,
                'write': True,
                'quiet_fallback': 'skip'
            },
            'match': {
                'preferred': {
                    'countries': ['US', 'GB', 'DE'],
                    'media': ['Digital Media|File', 'CD']
                }
            }
        }
        
        config_file = self.temp_dir / f'beets_config_{book_path.name}.yaml'
        with open(config_file, 'w') as f:
            yaml.dump(beets_config, f)
        
        # Run beets import on individual tracks
        cmd = [
            'beet', '-c', str(config_file), 'import', '-q', str(book_path)
        ]
        
        try:
            self.logger.info(f"Running beets command: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                self.logger.info("Beets tagging successful")
                
                # Re-extract metadata after beets processing
                updated_metadata = self.extract_metadata_from_files(book_path)
                if updated_metadata:
                    self.logger.info(f"Updated metadata - Artist: {updated_metadata['artist']}, Title: {updated_metadata['title']}")
                    return updated_metadata
                else:
                    self.logger.warning("Could not extract updated metadata, using initial")
                    return initial_metadata
            else:
                self.logger.warning(f"Beets tagging failed: {result.stderr}")
                return initial_metadata
                
        except subprocess.TimeoutExpired:
            self.logger.warning("Beets tagging timed out")
            return initial_metadata
        except Exception as e:
            self.logger.warning(f"Could not run beets: {str(e)}")
            return initial_metadata
        finally:
            # Clean up temporary config and database
            config_file.unlink(missing_ok=True)
            db_file = self.temp_dir / f'beets_{book_path.name}.db'
            db_file.unlink(missing_ok=True)
    
    def convert_to_m4b_ffmpeg712(self, book_path, metadata, output_filename):
        """Convert audiobook to M4B using FFmpeg 7.1.2 with libfdk_aac"""
        self.logger.info(f"Converting to M4B with FFmpeg 7.1.2: {book_path.name}")
        
        # Get all audio files sorted by name
        audio_files = sorted(list(book_path.glob("*.mp3")) + list(book_path.glob("*.m4a")))
        if not audio_files:
            self.logger.error("No audio files found")
            return None
        
        output_file = self.temp_dir / output_filename
        
        # Create file list for FFmpeg concat
        file_list_path = self.temp_dir / f"{book_path.name}_files.txt"
        with open(file_list_path, 'w') as f:
            for audio_file in audio_files:
                # Escape single quotes for ffmpeg
                escaped_path = str(audio_file.absolute()).replace("'", "'\"'\"'")
                f.write(f"file '{escaped_path}'\n")
        
        # FFmpeg 7.1.2 command with libfdk_aac and enhanced quality options
        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', str(file_list_path),
            '-c:a', self.config['conversion']['audio_codec'],
            '-b:a', self.config['conversion']['audio_bitrate'],
            '-movflags', '+faststart',
            '-metadata', f"title={metadata['title']}",
            '-metadata', f"artist={metadata['artist']}",
            '-metadata', f"album={metadata.get('album', metadata['title'])}",
        ]
        
        # Add year if available
        if metadata.get('year'):
            cmd.extend(['-metadata', f"year={metadata['year']}"])
        
        # Quality profile specific options for FFmpeg 7.1.2
        if self.config['conversion']['quality_profile'] == 'high':
            cmd.extend([
                '-afterburner', '1',
                '-cutoff', '20000',
                '-profile:a', 'aac_he_v2'
            ])
        elif self.config['conversion']['quality_profile'] == 'medium':
            cmd.extend(['-cutoff', '15000'])
        
        # Add cover art if available
        cover_files = (list(book_path.glob("cover.*")) + 
                      list(book_path.glob("folder.*")) + 
                      list(book_path.glob("*.jpg")) + 
                      list(book_path.glob("*.png")))
        if cover_files:
            cmd.extend(['-i', str(cover_files[0]), '-c:v', 'copy', '-disposition:v', 'attached_pic'])
        
        cmd.append(str(output_file))
        
        try:
            self.logger.info(f"Running FFmpeg 7.1.2 command: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            
            if result.returncode == 0 and output_file.exists():
                self.logger.info("M4B conversion successful with FFmpeg 7.1.2")
                
                # Clean up
                file_list_path.unlink(missing_ok=True)
                
                return output_file
            else:
                self.logger.error(f"FFmpeg conversion failed: {result.stderr}")
                return None
                
        except subprocess.TimeoutExpired:
            self.logger.error("FFmpeg conversion timed out")
            return None
        except Exception as e:
            self.logger.error(f"Error running FFmpeg 7.1.2: {str(e)}")
            return None

class AudiobookHandler(FileSystemEventHandler):
    """File system event handler for watching input directory"""
    
    def __init__(self, converter):
        self.converter = converter
    
    def on_created(self, event):
        if event.is_directory:
            # Wait for file copying to complete
            time.sleep(10)
            book_path = Path(event.src_path)
            audio_files = list(book_path.glob("*.mp3")) + list(book_path.glob("*.m4a"))
            if audio_files:
                self.converter.logger.info(f"New audiobook detected: {book_path}")
                self.converter.process_audiobook(book_path)

def main():
    """Main application entry point"""
    converter = AudiobookConverter()
    
    # Initial scan for existing books
    converter.scan_for_books()
    
    # Setup file system watcher
    event_handler = AudiobookHandler(converter)
    observer = Observer()
    observer.schedule(event_handler, str(converter.input_dir), recursive=True)
    observer.start()
    
    converter.logger.info("Audiobook converter started with FFmpeg 7.1.2. Watching for new files...")
    
    try:
        while True:
            time.sleep(60)  # Health check every minute
    except KeyboardInterrupt:
        observer.stop()
        converter.logger.info("Shutting down gracefully...")
    
    observer.join()

if __name__ == "__main__":
    main()