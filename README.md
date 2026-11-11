================================================================================================================================

#How To Use (If you haven't already, follow the instructions in the sections below this one, then come back when its all set up)

1) Once Fully configured press Start Pipeline you should see something like

	Starting pipeline scripts...
	[watch_anythingllm.py] Watching AnythingLLM storage: [your storage path]
	[watch_anythingllm.py] Outputting Markdown to: [vault path]/01-intake
	[intake_bot.py] 13:59:13  INFO     Watching [vault path]/01-intake

2) Starting the Process
	2.1)Either Drop a file directly into the Intake folder in Obsidian if it is a markdown file
	2.2)If it isn't a markdown file go to your workspace in anythingLLM click the upload symbol, and drag your document into the documents folder the storage path 	points to

	If it works you should see, which shows the file has been successfully converted to a markdown file and added to the intake folder:

		[watch_anythingllm.py] Extracted: Capabilities.docx-37c8ee31-d243-4088-871d-31306c34dad0.json -> Capabilities.md
		[intake_bot.py] 14:05:16  INFO     Processing: Capabilities.md
		[watch_anythingllm.py] Removed embeddings for: custom-documents/{filename]-37c8ee31-d243-4088-871d-31306c34dad0.json
		[watch_anythingllm.py] Deleted document file: custom-documents/[filename]-37c8ee31-d243-4088-871d-31306c34dad0.json
		[watch_anythingllm.py] Ignoring Markdown upload (loop prevention): Capabilities.md-270915b8-3666-4b2c-824f-dcaeb0fc0912.json

	This will also remove the inputted file, so it is only inputted once, simply exit the upload interface and when you reopen the interface you won't see anything 	in the upload portion

3) Simply wait for the document to process (should take a couple minutes, you should see the following in the app console when it is complete

	[intake_bot.py] 14:07:34  WARNING  Attempt 1 failed: Model returned an empty response
	[intake_bot.py] 14:08:32  INFO     Validation OK (attempt 2)
	[intake_bot.py] 14:08:32  INFO     Wrote note: [note name]
	[intake_bot.py] 14:08:35  INFO     Archived original \u2192 20261110-140835-[note-name]
	[watch_anythingllm.py] Ignoring Markdown upload (loop prevention): [note-name]-c5b91ecb-d2b6-4bb2-91f4-35d8865a6545.json

4) You should now be able to see the processed file in the 01-notes folder (to find the name, check the note-name in the app console)
Make sure to check the processed note for it's validity and that it has the correct tags.

================================================================================================================================

#Prerequisites


LLM Installation and RAG Setup
1) Install Ollama
2) Install model of your choice using ollama run [model name]
3) Install AnythingLLM
4) Select Ollama as LLM provider and select your installed model
5)Create Workspace you will be using 
6) Go to settings -> Developer API and generate new api key (save it as obsidian integration)


#Obsidian Setup
1) Install Obsidian
2) Setup the folder structure
	01-intake(where you add the document to process)
	01-notes(where your notes are stored
	02-processed(source files that have been added to the database)
	03-failed(where notes go if they do not get adequately sorted
3) Go to vault settings -> Community plugins
4) Search for and install AnythingLLMSync plugin
5) In the AnythingLLM URL field enter "http://localhost:3001" which is the default
6) In the Developer API Key field input the AnythingLLM API key you generated in the previous instruction
7) Press the test connection button, if you succeed move on to the next step, if it fails double check the API key and URL
8) Select your AnythingLLM document workspace
9) Set your watch folder to 01-notes

*Your Obsidian RAG system should now be set-up
*To Test go to your Anythingllm workspace
*Click the Upload button, you should see all the notes from the Obsidian storage on the right hand side

#Other Requirements
Install Python 

================================================================================================================================
#Obsidian Filing System Setup

Windows
1) Open the Start_Pipeline.bat file
2) Enter your Obsidian Vault path
3) To find this go to obsidian and right click the vault name and click Copy Path
4) Past in the Obsidian vault path field
5) Enter your AnythingLLM Storage Path
6) Navigate to appdata (Windows Key + r, enter %appdata%
7) Go to anythingllm-desktop\storage\documents\[documents folder]
8) Copy as path
9) Past in the Storage path field
10) Enter "http://localhost:3001" as the AnythingLLM URL this is the default, so long as you haven't changed it, this should always be the case
11) In the API key section paste in the key you generated in AnythingLLM Earlier
12) Finally enter the name of your workspace into the Workspace slug Field. This should by all lower case and whitespace should be represented by a hyphen
	*i.e. (My Workspace -> my-workspace
13) Press Save Config

macOS
1) Open the mac terminal and run: chmod +x Start_Pipeline.command
2) Double click application
3) Enter your Obsidian Vault path
4) To find this go to obsidian and right click the vault name and click Copy Path
5) Past in the Obsidian vault path field
6) Enter Your AnythingLLM Storage Path
7) Enter "http://localhost:3001" as the AnythingLLM URL this is the default, so long as you haven't changed it, this should always be the case
8) In the API key section paste in the key you generated in AnythingLLM Earlier
9) Finally enter the name of your workspace into the Workspace slug Field. This should by all lower case and whitespace should be represented by a hyphen
	*i.e. (My Workspace -> my-workspace
10) Press Save Config
