import streamlit as st
import zipfile
import os
from io import BytesIO
from time import sleep
import csv
from curl_cffi import requests as curl_requests
import pyproj
import glob
from geopy.geocoders import Nominatim

# Configuration
BASE_URL_L3 = "https://egms.land.copernicus.eu/insar-api/archive/download/EGMS_{data_type}_E{e}N{n}_100km_{d}_{year}_1.zip?id={id}"
BASE_URL_L2 = "https://egms.land.copernicus.eu/insar-api/archive/download/EGMS_{data_type}_{relative_orbit}_{burst_cycle}_{swath}_{polarization}_{year}_1.zip?id={id}"
DISPLACEMENTS = ["E", "U"]
DELAY = 3.0  # seconds between requests
DEFAULT_YEAR = "2019_2023"
DEFAULT_ID = "fcf61f768a6141ca81d6e4851c86cf89"

# Initialize session state variables
if 'download_status' not in st.session_state:
    st.session_state.download_status = ""
if 'current_progress' not in st.session_state:
    st.session_state.current_progress = 0
if 'total_tasks' not in st.session_state:
    st.session_state.total_tasks = 0
if 'download_ready' not in st.session_state:
    st.session_state.download_ready = False
if 'download_data' not in st.session_state:
    st.session_state.download_data = None
if 'download_filename' not in st.session_state:
    st.session_state.download_filename = ""

# Coordinate transformation setup - ETRS89 / LAEA Europe (EPSG:3035) to WGS84 (EPSG:4326)
@st.cache_resource
def init_transformer():
    try:
        return pyproj.Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
    except Exception as e:
        st.warning(f"Could not initialize coordinate transformer: {e}")
        return None

def convert_coordinates(easting, northing, transformer=None):
    """Convert easting/northing coordinates to latitude/longitude"""
    if transformer is None:
        # Fallback to initialize transformer if not provided
        transformer = init_transformer()
        if transformer is None:
            return None, None
    
    try:
        # Transform from projected coordinates to lat/lon
        lon, lat = transformer.transform(float(easting), float(northing))
        return lat, lon
    except Exception as e:
        st.error(f"Error converting coordinates: {e}")
        return None, None

def fetch_file_data(e, n, d, data_type="L3", year=DEFAULT_YEAR, id=DEFAULT_ID, relative_orbit=None, burst_cycle=None, swath=None, polarization=None):
    """Fetch file data for browser download"""
    
    if data_type == "L3":
        tile_code = f"E{e}N{n}"
        filename_prefix = f"EGMS_{data_type}_{tile_code}_100km_{d}_{year}_1"
        url = BASE_URL_L3.format(data_type=data_type, e=e, n=n, d=d, year=year, id=id)
    else:
        if not all([relative_orbit, burst_cycle, swath, polarization]):
            st.error(f"Missing parameters for {data_type} download")
            return None, None
        
        filename_prefix = f"EGMS_{data_type}_{relative_orbit}_{burst_cycle}_{swath}_{polarization}_{year}_1"
        url = BASE_URL_L2.format(
            data_type="L2a" if data_type == "L2A" else "L2b", 
            relative_orbit=relative_orbit, 
            burst_cycle=burst_cycle, 
            swath=swath, 
            polarization=polarization, 
            year=year, 
            id=id
        )
    
    try:
        with st.spinner(f"Fetching {filename_prefix}..."):
            response = curl_requests.get(url, timeout=3000)
            
            if response.status_code != 200:
                st.error(f"Failed to fetch {filename_prefix} (Status: {response.status_code})")
                return None, None
            
            # Extract CSV from zip in memory
            with zipfile.ZipFile(BytesIO(response.content)) as z:
                for name in z.namelist():
                    if name.endswith(".csv") and filename_prefix in name:
                        csv_data = z.read(name)
                        csv_filename = name
                        st.success(f"Successfully fetched {csv_filename}")
                        return csv_data, csv_filename
            
            st.error(f"No matching CSV found in the downloaded zip for {filename_prefix}")
            return None, None
    
    except Exception as e:
        st.error(f"Error fetching {filename_prefix}: {e}")
        return None, None

def create_batch_zip(files_data, batch_name):
    """Create a zip file containing multiple CSV files"""
    zip_buffer = BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for filename, data in files_data:
            if data is not None:
                zip_file.writestr(filename, data)
    
    zip_buffer.seek(0)
    return zip_buffer.getvalue()

def main():
    st.set_page_config(
        page_title="EGMSweb",
        initial_sidebar_state="expanded",
        page_icon="🌍",
        layout="wide"
    )
    
    # Reduce top padding with custom CSS
    st.markdown("""
        <style>
        .main .block-container {
            padding-top: 0rem;
            padding-bottom: 0rem;
        }
        .stApp > header {
            background-color: transparent;
        }
        </style>
        """, unsafe_allow_html=True)
    
    st.title("🌍 EGMSweb")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("Developed by Dr. Abidhan Bardhan (abidhan@nitp.ac.in)")
        
        rad_col1, rad_col2 = st.columns(2)
        
        with rad_col1:
            data_type = st.radio(
            "Select level",
            ["L2A", "L2B", "L3"],
            index=2,  # Default to L3
            horizontal=True
            )
        
        with rad_col2:
            download_type = st.radio(
                "Choose download type",
                ["Single File", "Batch Download"],
                horizontal=True
            )
        
        if download_type == "Single File":
            
            if data_type in ["L2A", "L2B"]:
                st.markdown("""Select L2a/L2b parameters""")
                
                # Parameters horizontally aligned
                col_param1, col_param2, col_param3, col_param4 = st.columns(4)
                
                with col_param1:
                    burst_cycle = st.text_input("Burst Cycle", value="0716")
                
                with col_param2:
                    polarization = st.selectbox("Polarization", ["VV", "VH", "HH", "HV"], index=0)
                
                with col_param3:
                    relative_orbit = st.text_input("Relative Orbit", value="052")
                
                with col_param4:
                    swath = st.selectbox("Swath", ["IW1", "IW2", "IW3"], index=1)
                
                # Year and Token horizontally aligned
                col_year, col_token = st.columns(2)
                
                with col_year:
                    year = st.selectbox(
                        "Year range",
                        ["2018_2022", "2019_2023", "2020_2024"],
                        index=1
                    )
                
                with col_token:
                    id_value = st.text_input("Token", value=DEFAULT_ID)
                
                # Download button
                if st.button("🔄 Prepare Download", key="prepare_l2_single"):
                    csv_data, csv_filename = fetch_file_data(0, 0, "", data_type, year, id_value, relative_orbit, burst_cycle, swath, polarization)
                    if csv_data and csv_filename:
                        st.session_state.download_data = csv_data
                        st.session_state.download_filename = csv_filename
                        st.session_state.download_ready = True
                
                # Show download button if data is ready
                if st.session_state.download_ready and st.session_state.download_data:
                    st.download_button(
                        label="💾 Download File",
                        data=st.session_state.download_data,
                        file_name=st.session_state.download_filename,
                        mime="text/csv",
                        key="download_l2_single"
                    )
                    
            else:  # L3
                st.markdown("""Select L3 parameters""")
                
                # L3 coordinates and displacement type horizontally aligned
                col_n, col_e, col_disp, _ = st.columns(4)
                with col_n:
                    n_coord = st.number_input("North", min_value=9, max_value=55, value=31)
                with col_e:
                    e_coord = st.number_input("East", min_value=9, max_value=65, value=32)
                with col_disp:
                    disp_choice = st.radio(
                        "Displacement type",
                        ["E", "U", "Both"], horizontal=True
                    )
                
                col_year, col_token = st.columns(2)
                with col_year:
                    year = st.selectbox(
                        "Year range",
                        ["2018_2022", "2019_2023", "2020_2024"],
                        index=1
                    )
                
                with col_token:
                    id_value = st.text_input("Token", value=DEFAULT_ID)
                
                # Download button
                if st.button("🔄 Prepare Download", key="prepare_l3_single"):
                    if disp_choice == "Both":
                        displacements = ["E", "U"]
                    else:
                        displacements = [disp_choice]
                    
                    files_data = []
                    progress_bar = st.progress(0)
                    status_placeholder = st.empty()
                    
                    for i, d in enumerate(displacements):
                        progress = i / len(displacements)
                        progress_bar.progress(progress)
                        status_placeholder.text(f"Fetching {d} displacement data...")
                        
                        csv_data, csv_filename = fetch_file_data(e_coord, n_coord, d, "L3", year, id_value)
                        if csv_data and csv_filename:
                            files_data.append((csv_filename, csv_data))
                        
                        sleep(1)  # Brief delay between requests
                    
                    progress_bar.progress(1.0)
                    status_placeholder.text("Preparing download...")
                    
                    if files_data:
                        if len(files_data) == 1:
                            # Single file
                            st.session_state.download_data = files_data[0][1]
                            st.session_state.download_filename = files_data[0][0]
                        else:
                            # Multiple files - create zip
                            zip_name = f"EGMS_L3_E{e_coord}N{n_coord}_{year}_batch.zip"
                            zip_data = create_batch_zip(files_data, zip_name)
                            st.session_state.download_data = zip_data
                            st.session_state.download_filename = zip_name
                        
                        st.session_state.download_ready = True
                        status_placeholder.text("✅ Ready for download!")
                
                # Show download button if data is ready
                if st.session_state.download_ready and st.session_state.download_data:
                    file_type = "application/zip" if st.session_state.download_filename.endswith('.zip') else "text/csv"
                    st.download_button(
                        label="💾 Download File",
                        data=st.session_state.download_data,
                        file_name=st.session_state.download_filename,
                        mime=file_type,
                        key="download_l3_single"
                    )
        
        else:  # Batch Download
            
            if data_type == "L3":
                col1batch, col2batch, col3batch , col4batch = st.columns(4)
                with col1batch:
                    min_n = st.number_input("Min North", min_value=9, max_value=55, value=25)
                with col2batch:
                    min_e = st.number_input("Min East", min_value=9, max_value=65, value=10)
                with col3batch:
                    max_n = st.number_input("Max North", min_value=9, max_value=55, value=26)
                with col4batch:
                    max_e = st.number_input("Max East", min_value=9, max_value=65, value=11)
                
                disp_choice = st.radio(
                    "Displacement type (batch)",
                    ["E", "U", "Both"],
                    horizontal=True
                )
                
                col_year, col_token = st.columns(2)
                with col_year:
                    year = st.selectbox(
                        "Year range",
                        ["2018_2022", "2019_2023", "2020_2024"],
                        index=1,
                        key="batch_year"
                    )
                
                with col_token:
                    id_value = st.text_input("Token", value=DEFAULT_ID, key="batch_token")
                
                total_tiles = (max_e - min_e + 1) * (max_n - min_n + 1)
                if disp_choice == "Both":
                    total_files = total_tiles * 2
                else:
                    total_files = total_tiles
                
                st.info(f"This will attempt to download {total_files} files from {total_tiles} tiles")
                
                if st.button("🔄 Prepare Batch Download", key="prepare_l3_batch"):
                    if disp_choice == "Both":
                        displacements = ["E", "U"]
                    else:
                        displacements = [disp_choice]
                    
                    files_data = []
                    progress_bar = st.progress(0)
                    status_placeholder = st.empty()
                    
                    total_tasks = (max_e - min_e + 1) * (max_n - min_n + 1) * len(displacements)
                    task_count = 0
                    
                    for e in range(min_e, max_e + 1):
                        for n in range(min_n, max_n + 1):
                            for d in displacements:
                                task_count += 1
                                progress = task_count / total_tasks
                                progress_bar.progress(progress)
                                status_placeholder.text(f"Fetching E{e}N{n} {d} ({task_count}/{total_tasks})")
                                
                                csv_data, csv_filename = fetch_file_data(e, n, d, "L3", year, id_value)
                                if csv_data and csv_filename:
                                    files_data.append((csv_filename, csv_data))
                                
                                sleep(1)  # Brief delay between requests
                    
                    progress_bar.progress(1.0)
                    status_placeholder.text("Creating batch download...")
                    
                    if files_data:
                        zip_name = f"EGMS_L3_E{min_e}-{max_e}_N{min_n}-{max_n}_{year}_batch.zip"
                        zip_data = create_batch_zip(files_data, zip_name)
                        st.session_state.download_data = zip_data
                        st.session_state.download_filename = zip_name
                        st.session_state.download_ready = True
                        status_placeholder.text(f"✅ Ready! {len(files_data)} files prepared for download")
                    else:
                        status_placeholder.text("❌ No files could be downloaded")
                
                # Show download button if data is ready
                if st.session_state.download_ready and st.session_state.download_data and st.session_state.download_filename.endswith('.zip'):
                    st.download_button(
                        label="💾 Download Batch ZIP",
                        data=st.session_state.download_data,
                        file_name=st.session_state.download_filename,
                        mime="application/zip",
                        key="download_l3_batch"
                    )
            
            else:  # L2a/L2b batch

                col_batch11, col_batch22,col_batch33,col_batch44 = st.columns(4)
                
                with col_batch11:
                    min_relative_orbit = st.number_input("Min Relative Orbit", min_value=1, max_value=999, value=50)
                with col_batch22:
                    max_relative_orbit = st.number_input("Max Relative Orbit", min_value=1, max_value=999, value=52)
                
                with col_batch33:
                    min_burst_cycle = st.number_input("Min Burst Cycle", min_value=1, max_value=9999, value=715)
                with col_batch44:
                    max_burst_cycle = st.number_input("Max Burst Cycle", min_value=1, max_value=9999, value=717)
                
                # Multi-select for swaths and polarizations
                swath_col1, swath_col2 = st.columns(2)
                with swath_col1:
                    selected_swaths = st.multiselect(
                        "Select Swaths", 
                        ["IW1", "IW2", "IW3"], 
                        default=["IW1", "IW2", "IW3"]
                    )
                with swath_col2:
                    selected_polarizations = st.multiselect(
                        "Select Polarizations", 
                        ["VV", "VH", "HH", "HV"], 
                        default=["VV"]
                    )
                
                col_year, col_token = st.columns(2)
                with col_year:
                    year = st.selectbox(
                        "Year range",
                        ["2018_2022", "2019_2023", "2020_2024"],
                        index=1,
                        key="batch_l2_year"
                    )
                
                with col_token:
                    id_value = st.text_input("Token", value=DEFAULT_ID, key="batch_l2_token")
                
                # Calculate total combinations
                orbit_count = max_relative_orbit - min_relative_orbit + 1
                burst_count = max_burst_cycle - min_burst_cycle + 1
                swath_count = len(selected_swaths)
                pol_count = len(selected_polarizations)
                total_combinations = orbit_count * burst_count * swath_count * pol_count
                
                st.info(f"This will attempt to download {total_combinations} files")
                
                if not selected_swaths or not selected_polarizations:
                    st.warning("Please select at least one swath and one polarization.")
                elif st.button("🔄 Prepare L2 Batch Download", key="prepare_l2_batch"):
                    files_data = []
                    progress_bar = st.progress(0)
                    status_placeholder = st.empty()
                    
                    task_count = 0
                    
                    for rel_orbit in range(min_relative_orbit, max_relative_orbit + 1):
                        for burst_cycle in range(min_burst_cycle, max_burst_cycle + 1):
                            for swath in selected_swaths:
                                for polarization in selected_polarizations:
                                    task_count += 1
                                    progress = task_count / total_combinations
                                    
                                    # Format with appropriate zero padding
                                    rel_orbit_str = f"{rel_orbit:03d}"
                                    burst_cycle_str = f"{burst_cycle:04d}"
                                    
                                    progress_bar.progress(progress)
                                    status_placeholder.text(f"Fetching {data_type}_{rel_orbit_str}_{burst_cycle_str}_{swath}_{polarization} ({task_count}/{total_combinations})")
                                    
                                    csv_data, csv_filename = fetch_file_data(
                                        0, 0, "", data_type, year, id_value, 
                                        rel_orbit_str, burst_cycle_str, swath, polarization
                                    )
                                    if csv_data and csv_filename:
                                        files_data.append((csv_filename, csv_data))
                                    
                                    sleep(1)  # Brief delay between requests
                    
                    progress_bar.progress(1.0)
                    status_placeholder.text("Creating batch download...")
                    
                    if files_data:
                        zip_name = f"EGMS_{data_type}_batch_{year}.zip"
                        zip_data = create_batch_zip(files_data, zip_name)
                        st.session_state.download_data = zip_data
                        st.session_state.download_filename = zip_name
                        st.session_state.download_ready = True
                        status_placeholder.text(f"✅ Ready! {len(files_data)} files prepared for download")
                    else:
                        status_placeholder.text("❌ No files could be downloaded")
                
                # Show download button if data is ready
                if st.session_state.download_ready and st.session_state.download_data and st.session_state.download_filename.endswith('.zip'):
                    st.download_button(
                        label="💾 Download L2 Batch ZIP",
                        data=st.session_state.download_data,
                        file_name=st.session_state.download_filename,
                        mime="application/zip",
                        key="download_l2_batch"
                    )
    
    with col2:
        st.subheader("About EGMS Data")
        
        # Updated description section
        st.markdown("""
        The European Ground Motion Service (EGMS) provides information about ground movements across Europe.
        
        **Data Types:**
        - **L2a**: Basic processing level with SAR geometry parameters
        - **L2b**: Intermediate processing level with SAR geometry parameters  
        - **L3**: Advanced processing level with geographic coordinates
        
        **L2A/L2B Parameters:**
        - **Relative Orbit**: SAR satellite orbit number (e.g., 052)
        - **Burst Cycle**: Timing cycle identifier (e.g., 0716)
        - **Swath**: Interferometric Wide (IW) swath number (IW1, IW2, IW3)
        - **Polarization**: Radar wave polarization (VV, VH, HH, HV)
          
        **L3 Parameters:**
        - **E/N Coordinates**: Geographic tile coordinates (100x100 km tiles)
        - **Displacement Types:**
          - **E**: East-West displacement
          - **U**: Up-Down displacement
        
        """)

       

if __name__ == "__main__":
    main() 


# Run egms_web
# Step 1: python -m venv env    
# Step 2: .\env\Scripts\activate
# Step 3: pip install -r requirements.txt
# streamlit run egms_web.py