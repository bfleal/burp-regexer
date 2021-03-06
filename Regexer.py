from burp import IBurpExtender
from burp import IExtensionStateListener
from burp import IHttpListener
from burp import IMessageEditorController
from burp import IScopeChangeListener
from burp import ITab

from java.lang import Boolean
from java.lang import Integer
from java.lang import Short
from java.lang import String

from javax.swing import GroupLayout
from javax.swing import LayoutStyle

from javax.swing import JButton
from javax.swing import JFrame
from javax.swing import JLabel
from javax.swing import JOptionPane
from javax.swing import JPanel
from javax.swing import JScrollPane
from javax.swing import JSplitPane
from javax.swing import JTable
from javax.swing import JTabbedPane
from javax.swing import JTextArea
from javax.swing import JTextField
from javax.swing import ListSelectionModel
from javax.swing.table import DefaultTableModel
from javax.swing.table import AbstractTableModel

from java.util import Arrays
from java.util import ArrayList
from java.awt.event import MouseListener
from javax.swing.event import ChangeListener

import re
import os
import sys
import json
import platform
import threading
# from threading import Lock,Thread,enumerate
try:
    from exceptions_fix import FixBurpExceptions
except ImportError:
    pass


class BurpExtender(IBurpExtender, ITab, IHttpListener, IMessageEditorController, AbstractTableModel, IScopeChangeListener, IExtensionStateListener):

    def registerExtenderCallbacks(self, callbacks):
        print("Regexer v1.2")

        self._callbacks = callbacks
        self._helpers = callbacks.getHelpers()
        self._log = ArrayList()
        self._lock = threading.Lock()
        self._filePath = "" 
        sys.stdout = callbacks.getStdout()

        self.regexTableColumns = ["#", "Enabled", "In Scope", "Rule Name", "Regex Rule", "Description"]
        self.regexTableData = []
        self.loadSaveLocalFile()

        self._requestViewer = self._callbacks.createMessageEditor(self, False)
        self._responseViewer = self._callbacks.createMessageEditor(self, False)               

        self._jTextAreaLineMatched = JTextArea()
        self._jTextAreaLineMatched.setEditable(False)
        
        self._jTextAreaValueMatched = JTextArea()
        self._jTextAreaValueMatched.setEditable(False)
        
        self._jTextAreaAllResults = JTextArea()
        self._jTextAreaAllResults.setEditable(False)
        
        self._jTextAreaDetails = JTextArea()
        self._jTextAreaDetails.setColumns(50)
        self._jTextAreaDetails.setLineWrap(True)
        self._jTextAreaDetails.setEditable(False)

        self._jTableEntry = EntryTable(self)
        self._jTableRegex = RegexTable(self, self._jTableEntry)        

        print("Processing proxy history, please wait...")
        threading.Thread(target=self.processProxyHistory).start()
        print("Done!")

        self._callbacks.setExtensionName("Regexer")
        self._callbacks.addSuiteTab(self)
        self._callbacks.registerHttpListener(self)        
        self._callbacks.registerScopeChangeListener(self) 
        self._callbacks.registerExtensionStateListener(self)
        return

    def getTabCaption(self):
        return "Regexer"

    def getUiComponent(self):
        regexer = Regexer(self)
        return regexer.jPanelMain

    def processHttpMessage(self, toolFlag, messageIsRequest, messageInfo):
        if messageIsRequest:
            return
        self._lock.acquire()
        self.processMessage(toolFlag, self._callbacks.saveBuffersToTempFiles(messageInfo))
        self._lock.release()   

    def processProxyHistory(self, regexUpdate=None):
        proxyHistory = self._callbacks.getProxyHistory()
        for messageInfo in proxyHistory:
            self._lock.acquire()
            self.processMessage(4, self._callbacks.saveBuffersToTempFiles(messageInfo), regexUpdate)
            self._lock.release()   

    def processMessage(self, toolFlag, messageInfo, regexUpdate=None):
        if not messageInfo.getResponse():
            return 

        requestInfo = self._helpers.analyzeRequest(messageInfo.getRequest())
        requestHeader = requestInfo.getHeaders()
        requestBody = messageInfo.getRequest()[(requestInfo.getBodyOffset()):].tostring()
        responseInfo = self._helpers.analyzeResponse(messageInfo.getResponse())
        responseHeader = responseInfo.getHeaders()
        responseBody = messageInfo.getResponse()[(responseInfo.getBodyOffset()):].tostring()
        headers = requestLines = responseLines = []
        if requestHeader or responseHeader:
            headers = requestHeader + responseHeader
        if requestBody:
            requestLines = [line + '\n' for line in requestBody.split('\n')]
        if responseBody:
            responseLines = [line + '\n' for line in responseBody.split('\n')]
        self.processRegex(toolFlag, messageInfo, headers + requestLines + responseLines, regexUpdate)

    def processRegex(self, toolFlag, messageInfo, lines, regexUpdate=None):
        if regexUpdate is None: 
            regexTableData = self._jTableRegex.getModel().getDataVector()
        else:
            regexTableData = ArrayList()
            regexTableData.add(Arrays.asList(-1, regexUpdate['enabled'], regexUpdate['inscope'], regexUpdate['key'], regexUpdate['regex']))
        
        for regex in regexTableData:
            enabled = regex.get(1)
            if not enabled:
                continue

            inscope = regex.get(2)
            url = self._helpers.analyzeRequest(messageInfo).getUrl()
            if inscope and not self._callbacks.isInScope(url):
                continue
            
            key = regex.get(3)
            regexPattern = regex.get(4)
            insertMessage = False

            if key not in REGEX_DICT:
                REGEX_DICT[key] = {}
            if 'valueMatched' not in REGEX_DICT[key]:
                REGEX_DICT[key]['valueMatched'] = []
            if 'lineMatched' not in REGEX_DICT[key]:
                REGEX_DICT[key]['lineMatched'] = []                        
            if 'logEntry' not in REGEX_DICT[key]:
                REGEX_DICT[key]['logEntry'] = ArrayList()
            
            valueMatched = []
            lineMatched = []
            for line in lines:
                resultRegex = re.findall("{}".format(regexPattern), line)
                if resultRegex:
                    insertMessage = True
                    if line not in lineMatched:
                        lineMatched.append(line[:300])                    
                    for result in resultRegex:
                        if result not in valueMatched:
                            valueMatched.append(result)        
                    
            if insertMessage:
                logEntries = REGEX_DICT[key]['logEntry']
                row = len(logEntries)
                url = self._helpers.analyzeRequest(messageInfo).getUrl()
                method = self._helpers.analyzeRequest(messageInfo).getHeaders()[0].split(" ")[0]
                logEntry = LogEntry(
                    row, 
                    toolFlag, 
                    self._callbacks.saveBuffersToTempFiles(messageInfo), 
                    url, 
                    method,
                    lineMatched,
                    valueMatched)
                if logEntry not in logEntries:
                    REGEX_DICT[key]['logEntry'].add(logEntry)                          

            REGEX_DICT[key]['valueMatched'] += valueMatched
            REGEX_DICT[key]['lineMatched'] += lineMatched

    def loadSaveLocalFile(self):
        global REGEX_DICT
        system = platform.system()
        if system == "Java":
            system = platform.java_ver()[3][0].split(" ")[0]
        if "Windows" in system:
            self._filePath = "C:\\WINDOWS\\Temp\\regexer-rules.json"
        elif "Linux" in system:
            self._filePath = "/tmp/regexer-rules.json" 
        elif "Darwin" in system:
            self._filePath = "~/Library/Caches/TemporaryItems/regexer-rules.json"
            
        if (os.path.isfile(self._filePath)):
            print("Loading regex from {}...".format(self._filePath))
            try:
                with open(self._filePath, "r") as file:
                    REGEX_DICT = json.load(file)
            except Exception as e:
                print("Something wrong while trying to load or parse file. Error: {}".format(e))
        else:
            print("Saving regex rules locally at {}...".format(self._filePath))
            for key in REGEX_DICT.keys():
                REGEX_DICT[key]['enabled'] = True
                REGEX_DICT[key]['intarget'] = False
            try:
                with open(self._filePath, "w") as file:
                    json.dump(REGEX_DICT, file)
            except Exception as e:
                print("Something wrong while trying to save file. Error: {}".format(e))  

        for key in REGEX_DICT.keys():
            self.regexTableData.append([
                len(self.regexTableData),
                REGEX_DICT[key]['enabled'],
                REGEX_DICT[key]['intarget'],
                key,
                REGEX_DICT[key]['regex'],
                REGEX_DICT[key]['description'],
            ])

    def getRowCount(self):
        try:
            return self._log.size()
        except:
            return 0

    def getColumnCount(self):
        return 4

    def getColumnName(self, columnIndex):
        if columnIndex == 0:
            return "#"
        if columnIndex == 1:
            return "Tool"
        if columnIndex == 2:
            return "Method"
        if columnIndex == 3:
            return "URI"
        return ""

    def getColumnClass(self, columnIndex):
        columnClasses = [Integer, String, String, String]
        return columnClasses[columnIndex]

    def getValueAt(self, rowIndex, columnIndex):
        logEntry = self._log.get(rowIndex)
        if columnIndex == 0:
            return logEntry._index
        if columnIndex == 1:
            return self._callbacks.getToolName(logEntry._tool)
        if columnIndex == 2:
            return logEntry._method
        if columnIndex == 3:
            return logEntry._url.toString()
        return ""

    def getHttpService(self):
        return self._currentlyDisplayedItem.getHttpService()

    def getRequest(self):
        return self._currentlyDisplayedItem.getRequest()

    def getResponse(self):
        return self._currentlyDisplayedItem.getResponse()

    def scopeChanged(self):        
        return 

    def extensionUnloaded(self):
        system = platform.system()
        if system == "Java":
            system = platform.java_ver()[3][0].split(" ")[0]
        if "Windows" in system:
            self._filePath = "C:\\WINDOWS\\Temp\\regexer-rules.json"
        elif "Linux" in system:
            self._filePath = "/tmp/regexer-rules.json" 
        elif "Darwin" in system:
            self._filePath = "~/Library/Caches/TemporaryItems/regexer-rules.json"        
        if os.path.exists(self._filePath ):
            os.remove(self._filePath)


class Regexer(JFrame):

    def __init__(self, extender):
        self._extender = extender
        self.jTableEntry = self._extender._jTableEntry
        self.jTableRegex = self._extender._jTableRegex

        self.jPanelMain = JPanel()
        self.jSplitPane1 = JSplitPane()
        self.jSplitPane2 = JSplitPane()
        self.jScrollPaneTableRegex = JScrollPane()
        self.jScrollPaneLineMatched = JScrollPane()
        self.jScrollPaneAllResults = JScrollPane()
        self.jScrollPaneDetails = JScrollPane()
        self.jScrollPaneTableEntry = JScrollPane()
        self.jScrollPaneValueMatched = JScrollPane()
        self.jTabbedPane = JTabbedPane()
        self.jTabbedPane2 = JTabbedPane();
        self.jPanelRequest = JPanel()
        self.jPanelResponse = JPanel()

        self.jButtonAdd = JButton("Add", actionPerformed=self.handleJButtonAdd)
        self.jButtonRemove = JButton("Remove", actionPerformed=self.handleJButtonRemove)
        self.jButtonEdit = JButton("Edit", actionPerformed=self.handleJButtonEdit)
        self.jButtonClear = JButton("Clear", actionPerformed=self.handleJButtonClear)
        self.jButtonUpdate = JButton("Update", actionPerformed=self.handleJButtonUpdate)

        self.jScrollPaneTableEntry.setViewportView(self.jTableEntry)
        self.jScrollPaneTableRegex.setViewportView(self.jTableRegex)

        self.jTabbedPane.addTab("Request", self._extender._requestViewer.getComponent())
        self.jTabbedPane.addTab("Response", self._extender._responseViewer.getComponent())

        self.jScrollPaneLineMatched.setViewportView(self._extender._jTextAreaLineMatched)
        self.jTabbedPane.addTab("Line Matched", self.jScrollPaneLineMatched)

        self.jScrollPaneValueMatched.setViewportView(self._extender._jTextAreaValueMatched)
        self.jTabbedPane.addTab("Value Matched", self.jScrollPaneValueMatched)

        self.jTabbedPane2.addTab("History", self.jSplitPane2)

        self.jScrollPaneAllResults.setViewportView(self._extender._jTextAreaAllResults)
        self.jTabbedPane2.addTab("All Results", self.jScrollPaneAllResults)

        self.jScrollPaneDetails.setViewportView(self._extender._jTextAreaDetails)
        self.jTabbedPane2.addTab("Details", self.jScrollPaneDetails)

        self.jTabbedPane2.addChangeListener(JTabbedPane2ChangeListener(self._extender, self.jTableRegex)) 

        self.jSplitPane2.setLeftComponent(self.jScrollPaneTableEntry)
        self.jSplitPane2.setRightComponent(self.jTabbedPane)

        self.jSplitPane1.setOrientation(JSplitPane.VERTICAL_SPLIT)
        self.jSplitPane1.setTopComponent(self.jScrollPaneTableRegex)
        self.jSplitPane1.setRightComponent(self.jTabbedPane2)

        layout = GroupLayout(self.jPanelMain)
        self.jPanelMain.setLayout(layout)
        layout.setHorizontalGroup(
            layout.createParallelGroup(GroupLayout.Alignment.LEADING)
            .addGroup(layout.createSequentialGroup()
                .addGap(6, 6, 6)
                .addGroup(layout.createParallelGroup(GroupLayout.Alignment.LEADING, False)
                    .addComponent(self.jButtonUpdate, GroupLayout.DEFAULT_SIZE, GroupLayout.DEFAULT_SIZE, Short.MAX_VALUE)
                    .addComponent(self.jButtonClear, GroupLayout.DEFAULT_SIZE, GroupLayout.DEFAULT_SIZE, Short.MAX_VALUE)
                    .addComponent(self.jButtonEdit, GroupLayout.DEFAULT_SIZE, GroupLayout.DEFAULT_SIZE, Short.MAX_VALUE)
                    .addComponent(self.jButtonAdd, GroupLayout.DEFAULT_SIZE, GroupLayout.DEFAULT_SIZE, Short.MAX_VALUE)
                    .addComponent(self.jButtonRemove, GroupLayout.DEFAULT_SIZE, 86, Short.MAX_VALUE))
                .addPreferredGap(LayoutStyle.ComponentPlacement.RELATED)
                .addComponent(self.jSplitPane1))
        )
        layout.setVerticalGroup(
            layout.createParallelGroup(GroupLayout.Alignment.LEADING)
            .addGroup(layout.createSequentialGroup()
                .addComponent(self.jButtonAdd, GroupLayout.PREFERRED_SIZE, 28, GroupLayout.PREFERRED_SIZE)
                .addGap(4, 4, 4)
                .addComponent(self.jButtonEdit, GroupLayout.PREFERRED_SIZE, 28, GroupLayout.PREFERRED_SIZE)
                .addGap(4, 4, 4)
                .addComponent(self.jButtonRemove, GroupLayout.PREFERRED_SIZE, 28, GroupLayout.PREFERRED_SIZE)
                .addGap(56, 56, 56)
                .addComponent(self.jButtonClear, GroupLayout.PREFERRED_SIZE, 28, GroupLayout.PREFERRED_SIZE)
                .addGap(4, 4, 4)
                .addComponent(self.jButtonUpdate, GroupLayout.PREFERRED_SIZE, 28, GroupLayout.PREFERRED_SIZE)
                .addContainerGap(GroupLayout.DEFAULT_SIZE, Short.MAX_VALUE))
            .addComponent(self.jSplitPane1, GroupLayout.DEFAULT_SIZE, 603, Short.MAX_VALUE)
        )          

    def handleJButtonAdd(self, event):
        regexerEdit = RegexerEdit(self._extender, self.jTableRegex, event)
        regexerEdit.pack()
        regexerEdit.show()

    def handleJButtonEdit(self, event):
        regexerEdit = RegexerEdit(self._extender, self.jTableRegex, event)
        regexerEdit.pack()
        regexerEdit.show()

    def handleJButtonRemove(self, event):
        index = self.jTableRegex.convertRowIndexToModel(self.jTableRegex.getSelectedRow())
        if(index != -1):
            key = self.jTableRegex.getValueAt(index, 3)
            self.jTableRegex.removeRow(index)
            REGEX_DICT[key]['logEntry'] = ArrayList()
            REGEX_DICT[key]['valueMatched'] = []
            self._extender._log = ArrayList()
            self._extender._requestViewer.setMessage("None", True)
            self._extender._responseViewer.setMessage("None", True)
            self._extender._jTextAreaLineMatched.setText("None")
            self._extender._jTextAreaValueMatched.setText("None")
            self._extender._jTextAreaAllResults.setText("Select one rule from regex table to show it's results.")
            self._extender._jTextAreaDetails.setText("Select one rule from regex table to show it's results.")
            self.jTableEntry.getModel().fireTableDataChanged()
            JOptionPane.showMessageDialog(None, "Selected row successfully deleted!")
            try:
                regexTableData = self.jTableRegex.getModel().getDataVector()
                regexDict = {}
                for regex in regexTableData:
                    regexDict[regex[3]] = {"regex":regex[4], "description":regex[5]}
                with open(self._extender._filePath, "w") as file:
                    json.dump(regexDict, file)
            except Exception as e:
                print("Something wrong while trying to update file. Error: {}".format(e))              

    def handleJButtonClear(self, event):
        index = self.jTableRegex.getSelectedRow() 
        if(index != -1):
            key = self.jTableRegex.getValueAt(index, 3)
            regex = self.jTableRegex.getValueAt(index, 4)
            details = '''
                {} results found for this regex.\n
                {} uniq results show in 'All Results' tab.\n
                \nRule name: 
                {}
                \nRegex: 
                {}
            '''.format(0, 0, key, regex)
            if 'logEntry' in REGEX_DICT[key]:
                REGEX_DICT[key]['logEntry'] = ArrayList()
                REGEX_DICT[key]['valueMatched'] = []
                self._extender._log = ArrayList()
                self._extender._requestViewer.setMessage("None", True)
                self._extender._responseViewer.setMessage("None", True)
                self._extender._jTextAreaLineMatched.setText("None")
                self._extender._jTextAreaValueMatched.setText("None")
                self._extender._jTextAreaAllResults.setText("No results found for '{}' regex.".format(key))
                self._extender._jTextAreaDetails.setText("Select one rule from regex table to show it's results.") 
                self._extender._jTextAreaDetails.setText(details) 
                self.jTableEntry.getModel().fireTableDataChanged()
                JOptionPane.showMessageDialog(None, "Entries and results successfully cleared!")

    def handleJButtonUpdate(self, event):
        index = self.jTableRegex.getSelectedRow() 
        if(index != -1):
            enabled = self.jTableRegex.getValueAt(index, 1)
            if enabled:
                inscope = self.jTableRegex.getValueAt(index, 2)
                key = self.jTableRegex.getValueAt(index, 3)
                regex = self.jTableRegex.getValueAt(index, 4)
                if 'logEntry' in REGEX_DICT[key]:
                    REGEX_DICT[key]['logEntry'] = ArrayList()
                    REGEX_DICT[key]['valueMatched'] = []  
                threading.Thread(target=self._extender.processProxyHistory, args=({"enabled":enabled, "inscope":inscope, "key":key, "regex":regex},)).start()
                self._extender._log = REGEX_DICT[key]['logEntry']
                self.jTableEntry.getModel().fireTableDataChanged()
                threadAlive = True
                while threadAlive:
                    if len(threading.enumerate()) <= 1:
                        threadAlive = False

                if not threadAlive:
                    try:
                        logEntry = self._extender._log.get(0)
                        self._extender._requestViewer.setMessage(logEntry._requestResponse.getRequest(), True)
                        self._extender._responseViewer.setMessage(logEntry._requestResponse.getResponse(), True)
                        self._extender._jTextAreaLineMatched.setText("\n".join(str(line).encode("utf-8").strip() for line in logEntry._lineMatched))
                        self._extender._jTextAreaValueMatched.setText("\n".join(str(value).encode("utf-8").strip() for value in logEntry._valueMatched))
                        self._extender._jTextAreaAllResults.setText("\n".join(str(line).encode("utf-8").strip() for line in list(set(REGEX_DICT[key]['valueMatched']))))
                        self._extender._currentlyDisplayedItem = logEntry._requestResponse                            
                    except:
                        self._extender._requestViewer.setMessage("None", True)
                        self._extender._responseViewer.setMessage("None", True)
                        self._extender._jTextAreaLineMatched.setText("None")
                        self._extender._jTextAreaValueMatched.setText("None")   
                        self._extender._jTextAreaAllResults.setText("No results found for '{}' regex.".format(key))

                    length = len(REGEX_DICT[key]['valueMatched'])
                    uniq = len(list(set(REGEX_DICT[key]['valueMatched'])))
                    details = '''
                        {} results found for this regex.\n
                        {} uniq results show in 'All Results' tab.\n
                        \nRule name: 
                        {}
                        \nRegex: 
                        {}'''.format(length, uniq, key, regex)
                    self._extender._jTextAreaDetails.setText(details)                

class JTabbedPane2ChangeListener(ChangeListener):
    def __init__(self, extender, jTableRegex):
        self._extender = extender
        self.jTableRegex = jTableRegex

    def stateChanged(self, event):
        tab = event.getSource()
        index = tab.getSelectedIndex()
        title = tab.getTitleAt(index)
        
        if title == "All Results":
            try:
                key = self.jTableRegex.getValueAt(self.jTableRegex.getSelectedRow(), 3)
                if 'valueMatched' in REGEX_DICT[key] and  REGEX_DICT[key]['valueMatched'] != []:                
                    self._extender._jTextAreaAllResults.setText("\n".join(str(line).encode("utf-8").strip() for line in list(set(REGEX_DICT[key]['valueMatched']))))
                else: 
                    REGEX_DICT[key]['valueMatched'] = []
                    self._extender._jTextAreaAllResults.setText("No results found for '{}' regex.".format(key))
            except:
                self._extender._jTextAreaAllResults.setText("Select one rule from regex table to show it's results.")
        
        if title == "Details":
            try:
                key = self.jTableRegex.getValueAt(self.jTableRegex.getSelectedRow(), 3)
                regex = self.jTableRegex.getValueAt(self.jTableRegex.getSelectedRow(), 4)            
                length = len(REGEX_DICT[key]['valueMatched'])
                uniq = len(list(set(REGEX_DICT[key]['valueMatched'])))
                details = '''
                {} results found for this regex.\n
                {} uniq results show in 'All Results' tab.\n
                \nRule name: 
                {}
                \nRegex: 
                {}
                '''.format(length, uniq, key, regex)
                self._extender._jTextAreaDetails.setText(details)
            except:
                self._extender._jTextAreaDetails.setText("Select one rule from regex table to show it's results.")


class RegexerEdit(JFrame):

    def __init__(self, extender, jTableRegex, event):
        self._extender = extender
        self._event = event
        self.jTableRegex = jTableRegex
        
        self.jLabel1 = JLabel()
        self.jLabel1.setText("Specify the details of the regex rule.")
        
        self.jLabel2 = JLabel()
        self.jLabel2.setText("Rule Name:")
        
        self.jLabel3 = JLabel()
        self.jLabel3.setText("Regex:")
        
        self.jLabel4 = JLabel()
        self.jLabel4.setText("Description:")

        self.jTextFieldkey = JTextField()
        self.jTextFieldRegex = JTextField()
        self.jTextFieldDescription = JTextField()

        if event.source.text == "Add":
            self.setTitle("Add Regex Rule")
        elif event.source.text == "Edit":
            self.setTitle("Edit Regex Rule")
            self.jTextFieldkey.setText(self.jTableRegex.getValueAt(self.jTableRegex.getSelectedRow(), 3))
            self.jTextFieldRegex.setText(self.jTableRegex.getValueAt(self.jTableRegex.getSelectedRow(), 4))
        
        self.jButtonOk = JButton("OK", actionPerformed=self.addEditRegex)
        self.jButtonCancel = JButton("Cancel", actionPerformed=self.closeRegexerEdit)
        
        layout = GroupLayout(self.getContentPane())
        self.getContentPane().setLayout(layout)
        layout.setHorizontalGroup(
            layout.createParallelGroup(GroupLayout.Alignment.LEADING)
            .addGroup(layout.createSequentialGroup()
                .addGap(20, 20, 20)
                .addGroup(layout.createParallelGroup(GroupLayout.Alignment.LEADING)
                    .addComponent(self.jLabel1)
                    .addGroup(GroupLayout.Alignment.TRAILING, layout.createSequentialGroup()
                        .addComponent(self.jButtonOk, GroupLayout.PREFERRED_SIZE, 70, GroupLayout.PREFERRED_SIZE)
                        .addPreferredGap(LayoutStyle.ComponentPlacement.RELATED)
                        .addComponent(self.jButtonCancel, GroupLayout.PREFERRED_SIZE, 70, GroupLayout.PREFERRED_SIZE))
                    .addGroup(GroupLayout.Alignment.TRAILING, layout.createSequentialGroup()
                        .addGroup(layout.createParallelGroup(GroupLayout.Alignment.LEADING)
                            .addComponent(self.jLabel4)
                            .addComponent(self.jLabel3)
                            .addComponent(self.jLabel2))
                        .addGap(18, 18, 18)
                        .addGroup(layout.createParallelGroup(GroupLayout.Alignment.LEADING)
                            .addGroup(layout.createSequentialGroup()
                                .addComponent(self.jTextFieldkey, GroupLayout.PREFERRED_SIZE, 382, GroupLayout.PREFERRED_SIZE)
                                .addGap(16, 117, Short.MAX_VALUE))
                            .addComponent(self.jTextFieldRegex)
                            .addComponent(self.jTextFieldDescription))))
                .addContainerGap(20, Short.MAX_VALUE))
        )
        layout.setVerticalGroup(
            layout.createParallelGroup(GroupLayout.Alignment.LEADING)
            .addGroup(layout.createSequentialGroup()
                .addGap(20, 20, 20)
                .addComponent(self.jLabel1)
                .addGap(18, 18, 18)
                .addGroup(layout.createParallelGroup(GroupLayout.Alignment.BASELINE)
                    .addComponent(self.jTextFieldkey, GroupLayout.PREFERRED_SIZE, 24, GroupLayout.PREFERRED_SIZE)
                    .addComponent(self.jLabel2))
                .addPreferredGap(LayoutStyle.ComponentPlacement.UNRELATED)
                .addGroup(layout.createParallelGroup(GroupLayout.Alignment.BASELINE)
                    .addComponent(self.jLabel3)
                    .addComponent(self.jTextFieldRegex, GroupLayout.PREFERRED_SIZE, 24, GroupLayout.PREFERRED_SIZE))
                .addPreferredGap(LayoutStyle.ComponentPlacement.UNRELATED)
                .addGroup(layout.createParallelGroup(GroupLayout.Alignment.BASELINE)
                    .addComponent(self.jLabel4)
                    .addComponent(self.jTextFieldDescription, GroupLayout.PREFERRED_SIZE, 24, GroupLayout.PREFERRED_SIZE))
                .addGap(18, 18, 18)
                .addGroup(layout.createParallelGroup(GroupLayout.Alignment.TRAILING)
                    .addComponent(self.jButtonCancel, GroupLayout.PREFERRED_SIZE, 27, GroupLayout.PREFERRED_SIZE)
                    .addComponent(self.jButtonOk, GroupLayout.PREFERRED_SIZE, 27, GroupLayout.PREFERRED_SIZE))
                .addContainerGap(GroupLayout.DEFAULT_SIZE, Short.MAX_VALUE))
        )

    def addEditRegex(self, event):
        key =  self.jTextFieldkey.getText()
        regex = self.jTextFieldRegex.getText()
        description = self.jTextFieldDescription.getText()
        validRegex = False
        if key == "" or regex == "":
            JOptionPane.showMessageDialog(None, "Rule name and regex must not be empty!")
        else:
            try:
                re.compile(regex)
                validRegex = True
            except:
                JOptionPane.showMessageDialog(None, "Invalid regex. Verify your rule!")

        if  validRegex:
            if self._event.source.text == "Add":
                try:
                    lastIndex = self.jTableRegex.getValueAt(self.jTableRegex.getRowCount()-1, 0)
                except:
                    lastIndex = 0
                self.jTableRegex.addRow([lastIndex + 1, True, False, key, regex, description])            
                self.updateRegexDict(key, regex, description)
                self.dispose()
            elif self._event.source.text == "Edit":
                index = self.jTableRegex.getRowSorter().convertRowIndexToModel(self.jTableRegex.getSelectedRow())
                self.jTableRegex.setValueAt(key, index, 3)
                self.jTableRegex.setValueAt(regex, index, 4)
                self.jTableRegex.setValueAt(description, index, 5)
                self.updateRegexDict(key, regex, description)
                self.dispose()
            
            try:
                regexDict = {}
                regexTableData = self.jTableRegex.getModel().getDataVector()
                for regex in regexTableData:
                    regexDict[regex[3]] = {"enabled":regex[1], "intarget":regex[2], "regex":regex[4], "description":regex[5]}
                with open(self._extender._filePath, "w") as file:
                    json.dump(regexDict, file)
            except Exception as e:
                print("Something wrong while trying to update file. Error: {}".format(e))   


    def updateRegexDict(self, key, regex, description):
        if key not in REGEX_DICT:
            REGEX_DICT[key] = {}
        else: 
            REGEX_DICT[key]['regex'] = regex
            REGEX_DICT[key]['description'] = description

    def closeRegexerEdit(self, event):
        self.dispose()


class RegexTable(JTable):

    def __init__(self, extender, jTableEntry):
        self._extender = extender
        self._jTableEntry = jTableEntry
        model = RegexTableModel(self._extender.regexTableData, self._extender.regexTableColumns)

        self.setModel(model)
        self.setAutoCreateRowSorter(True)
        self.getTableHeader().setReorderingAllowed(False)
        self.setSelectionMode(ListSelectionModel.SINGLE_SELECTION)
        self.addMouseListener(RegexTableMouseListener(self._extender, self._jTableEntry))
        
        self.getColumnModel().getColumn(0).setMaxWidth(70)
        self.getColumnModel().getColumn(1).setMaxWidth(100)
        self.getColumnModel().getColumn(2).setMaxWidth(100)
        self.getColumnModel().getColumn(3).setPreferredWidth(300)
        self.getColumnModel().getColumn(4).setPreferredWidth(400)
        self.getColumnModel().getColumn(5).setPreferredWidth(500)
        self.setAutoResizeMode(JTable.AUTO_RESIZE_LAST_COLUMN)

    def addRow(self, data):
        self.getModel().addRow(data)

    def removeRow(self, row):
        self.getModel().removeRow(row)

    def setValueAt(self, value, row, column):
        row = self.convertRowIndexToModel(self.getSelectedRow())
        self.getModel().setValueAt(value, row, column)


class RegexTableModel(DefaultTableModel):

    def __init__(self, data, columns):
        DefaultTableModel.__init__(self, data, columns)

    def isCellEditable(self, row, column):
        canEdit = [False, True, True, False, False, False]
        return canEdit[column]

    def getColumnClass(self, column):
        columnClasses = [Integer, Boolean, Boolean, String, String, String]
        return columnClasses[column]


class RegexTableMouseListener(MouseListener):
    
    def __init__(self, extender, jTableEntry):
        self._extender = extender
        self._jTableEntry = jTableEntry

    def getClickedRow(self, event):
        regexTable = event.getSource()
        return regexTable.getModel().getDataVector().elementAt(regexTable.convertRowIndexToModel(regexTable.getSelectedRow()))

    def getClickedColumn(self, event):
        regexTable = event.getSource()
        return regexTable.getSelectedColumn()

    def getClickedIndex(self, event):
        regexTable = event.getSource()
        return regexTable.getValueAt(regexTable.convertRowIndexToModel(regexTable.getSelectedRow()), 0)

    def mouseClicked(self, event):
        regexTable = event.getSource()
        key = self.getClickedRow(event)[3]
        regex = self.getClickedRow(event)[4]  
        column = self.getClickedColumn(event)
        
        if 'logEntry' in REGEX_DICT[key]:
            self._extender._log = REGEX_DICT[key]['logEntry']
            self._jTableEntry.getModel().fireTableDataChanged()
            try:
                logEntry = self._extender._log.get(0)
                self._extender._requestViewer.setMessage(logEntry._requestResponse.getRequest(), True)
                self._extender._responseViewer.setMessage(logEntry._requestResponse.getResponse(), True)
                self._extender._jTextAreaLineMatched.setText("\n".join(str(line).encode("utf-8").strip() for line in logEntry._lineMatched))
                self._extender._jTextAreaValueMatched.setText("\n".join(str(value).encode("utf-8").strip() for value in logEntry._valueMatched))
                self._extender._currentlyDisplayedItem = logEntry._requestResponse       
            except:
                self._extender._requestViewer.setMessage("None", True)
                self._extender._responseViewer.setMessage("None", True)
                self._extender._jTextAreaLineMatched.setText("None")
                self._extender._jTextAreaValueMatched.setText("None")
        else:
            REGEX_DICT[key]['logEntry'] = ArrayList()

        try:
            if 'valueMatched' in REGEX_DICT[key] and  REGEX_DICT[key]['valueMatched'] != []:                
                self._extender._jTextAreaAllResults.setText(
                    "\n".join(str(line).encode("utf-8").strip() for line in list(set(REGEX_DICT[key]['valueMatched'])))
                )
            else: 
                REGEX_DICT[key]['valueMatched'] = []
                self._extender._jTextAreaAllResults.setText("No results found for '{}' regex.".format(key))
        except:
            self._extender._jTextAreaAllResults.setText("Select one rule from regex table to show it's results.")
           
        try:
            length = len(REGEX_DICT[key]['valueMatched'])
            uniq = len(list(set(REGEX_DICT[key]['valueMatched'])))
            details = '''
                {} results found for this regex.\n
                {} uniq results show in 'All Results' tab.\n
                \nRule name: 
                {}
                \nRegex: 
                {}
                '''.format(length, uniq, key, regex)
            self._extender._jTextAreaDetails.setText(details)
        except:
            self._extender._jTextAreaDetails.setText("Select one rule from regex table to show it's results.")    

        if column == 1 or column == 2:
            try:
                regexDict = {}
                regexTableData = regexTable.getModel().getDataVector()
                for regex in regexTableData:
                    regexDict[regex[3]] = {"enabled":regex[1], "intarget":regex[2], "regex":regex[4], "description":regex[5]}
                with open(self._extender._filePath, "w") as file:
                    json.dump(regexDict, file)
            except Exception as e:
                print("Something wrong while trying to update file. Error: {}".format(e))   
        

    def mousePressed(self, event):
        pass

    def mouseReleased(self, event):
        pass

    def mouseEntered(self, event):
        pass

    def mouseExited(self, event):
        pass


class EntryTable(JTable):

    def __init__(self, extender):
        self._extender = extender
        self.setModel(extender)
        self.setAutoCreateRowSorter(True)
        self.setSelectionMode(ListSelectionModel.SINGLE_SELECTION);
        self.getTableHeader().setReorderingAllowed(False)

    def changeSelection(self, row, col, toggle, extend):
        index = self.getValueAt(row, 0)
        logEntry = self._extender._log.get(index)
        self._extender._requestViewer.setMessage(logEntry._requestResponse.getRequest(), True)
        self._extender._responseViewer.setMessage(logEntry._requestResponse.getResponse(), True)
        self._extender._jTextAreaLineMatched.setText("\n".join(str(line).encode("utf-8").strip() for line in logEntry._lineMatched))
        self._extender._jTextAreaValueMatched.setText("\n".join(str(value).encode("utf-8").strip() for value in logEntry._valueMatched))
        self._extender._currentlyDisplayedItem = logEntry._requestResponse
        JTable.changeSelection(self, row, col, toggle, extend)  


class LogEntry:
    def __init__(self, index, tool, requestResponse, url, method, lineMatched, valueMatched):
        self._index = index
        self._tool = tool
        self._requestResponse = requestResponse
        self._url = url
        self._method = method
        self._lineMatched = lineMatched
        self._valueMatched = valueMatched


try:
    FixBurpExceptions()
except:
    pass


REGEX_DICT = {
    "AWS S3 URL": {
        "description": "",
        "regex": "https?://[a-zA-Z0-9-.]*s3.amazonaws.com[a-zA-Z0-9?=&\\[\\]:%_./-]*"
    },
    "URI Schemes": {
        "description": "",
        "regex": "[a-zA-Z0-9-]*://[a-zA-Z0-9?=&\\[\\]:%_./-]+"
    },
    "AWS Access Key": {
        "description": "",
        "regex": "AKIA[0-9A-Z]{16}"
    },
    "Token": {
        "description": "",
        "regex": "token=[a-zA-Z0-9.+/]+"
    },
    "Google API": {
        "description": "",
        "regex": "AIza[0-9A-Za-z-_]{35}"
    },
    "MD4/MD5": {
        "description": "",
        "regex": "([a-f0-9]{32})"
    },
    "HTML Comments": {
        "description": "",
        "regex": "(\\<![\\s]*--[\\-!@#$%^&*:;.,\"'(){}\\w\\s\\/\\[\\]]*--[\\s]*\\>)"
    },
    "Private Key": {
        "description": "",
        "regex": "Private Key: -----BEGIN PRIVATE KEY-----|-----END PRIVATE KEY-----"
    },
    "Paths": {
        "description": "",
        "regex": "['\"]/[a-zA-Z0-9/_-]+['\"]*"
    },
    "Email Adressess": {
        "description": "",
        "regex": "([a-zA-Z0-9_.+-]+@[a-zA-Z0-9]+[a-zA-Z0-9-]*\\.[a-zA-Z0-9-.]*[a-zA-Z0-9]{2,})"
    },
    "Internal IP Adressess": {
        "description": "",
        "regex": "172\.[1-3]{1}\d{0,2}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|127\.\d{1,3}\.\d{1,3}\.\d{1,3}|[fF][eE][89aAbBcCdDeEfF]::"
    },
    "RSA Key": {
        "description": "",
        "regex": "-----BEGIN RSA PRIVATE KEY-----|-----END RSA PRIVATE KEY-----"
    },
    "Top 25 Cross-Site Scripting (XSS) Parameters": {
        "description": "",
        "regex": "q=|s=|search=|id=|lang=|keyword=|query=|page=|keywords=|year=|view=|email=|type=|name=|p=|month=|image=|list_type=|url=|terms=|categoryid=|key=|l=|begindate=|enddate="
    },
    "Top 25 Server-Side Request Forgery (SSRF) Parameters": {
        "description": "",
        "regex": "dest=|redirect=|uri=|path=|continue=|url=|window=|next=|data=|reference=|site=|html=|val=|validate=|domain=|callback=|return=|page=|feed=|host=|port=|to=|out=|view=|dir="
    },
    "Top 25 Local File Inclusion (LFI) Parameters": {
        "description": "",
        "regex": "cat=|dir=|action|board=|date=|detail=|file=|download=|path|folder=|prefix=|include=|page=|inc=|locate=|show=|doc=|site=|type=|view=|content=|document=|layout=|mod=|conf="
    },
    "Top 25 SQL Injection Parameters": {
        "description": "",
        "regex": "id=|page=|report=|dir=|search=|category=|file=|class|url=|news=|item=|menu=|lang=|name=|ref=|title=|view=|topic=|thread=|type=|date=|form=|main=|nav=|region="
    },
    "Top 25 Remote Code Execution (RCE) Parameters": {
        "description": "",
        "regex": "cmd=|exec=|command=|execute=|ping=|query=|jump=|code|reg=|do=|func=|arg=|option=|load=|process=|step=|read=|feature=|exe=|module=|payload=|run=|print="
    },
    "Top 25 Open Redirect Parameters": {
        "description": "",
        "regex": "next=|url=|target=|rurl=|dest=|destination=|redir=|redirect_uri|redirect_url=|redirect=|out=|view=|to=|image_url=|go=|return=|returnTo=|return_to=|checkout_url=|continue=|return_path="
    }
}